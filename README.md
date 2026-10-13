# DLNA media servers as a Music Assistant source: research notes

*Research as of 2026-10-07, status updated 2026-10-09. Source-code links are pinned to the commit that was checked. Machine-readable data is in [`data/`](data/), and the script that produced the fork scan is in [`tools/`](tools/). Scope: whether DLNA/UPnP **media servers** (DMS, the ContentDirectory side) can serve as a source for Music Assistant (MA), what the protocol and real servers actually guarantee, what async_upnp_client's `DmsDevice` offers, and how MA could support playback from such servers.*

**Legend:** ✔ verified (specification or source code read) · ◐ vendor or secondary documentation · ✘ not verified, *assumption*

---

## 1. Summary

- **Importing a DMS as a full MA library (like Plex or a file share) is a poor fit.** The browse tree isn't standardised, search is optional, IDs are only *recommended* to be stable, and counts may be unknown. ✔
- **A browse- and search-only MA provider is feasible** with existing components: async_upnp_client's `DmsDevice` (already an MA dependency) and HA's `dlna_dms` integration as a reference. ✔
- **The most urgent library gap is paging.** `DmsDevice` fetches one page per call, and HA asks for everything in one request. Real servers cap responses (Twonky: 500 items, HA #113746; Windows: 204,800 bytes), so libraries silently appear incomplete. ✔
- **`DmsDevice` doesn't use the library's lenient DIDL parsing.** Malformed metadata raises instead of degrading; a WiiM/LinkPlay quirk exists in a fork. ✔
- **No existing issue, pull request or fork branch** (all 48 forks checked) works on these `DmsDevice` gaps. ✔
- **The opposite direction (MA as a DLNA renderer)** is covered by the add-on `ma-dlna-renderer` and MA draft PR #3611. ✔
- **Server support varies:**
  - most open-source servers support text search and counting (ReadyMedia, Gerbera, Jellyfin plugin, UMS) ✔;
  - Kodi searches only by class ✔;
  - closed-source servers (Plex, Emby, Serviio, JRiver) are unverified ✘.

---

## 2. Claims in MA discussion #890, checked

| Claim | Who | Verdict | Evidence |
|---|---|---|---|
| "The lack of a standard cannot be understated" | OzGav (maintainer) | **Partly true.** The protocol is standardised (UPnP AV ContentDirectory); how the content tree is organised and whether search exists are not. ✔ | CDS:1 §2.4, §2.7 |
| "DLNA does not prescribe how the media server should expose all its albums" | GioF71 | **True** ✔ | CDS:1 p. 7 ("logical collections … or … arbitrary collections"); MinimServer: "There's no UPnP standard for what the browse tree should look like" |
| "You can get to the same album in a multitude of ways" | GioF71 | **True** ✔ | Reference items (`refID`), CDS:4 §5.2.21; MinimServer tag browsing |
| "Scanning a DLNA media server might never end" | GioF71 | **Overstated.** Trees are finite but can be huge and redundant. With Search, `upnp:class derivedfrom "object.item.audioItem"` lists every audio item once. ✔ | CDS:1 search syntax; ReadyMedia code |
| "There is no standard way to list the complete contents" | GioF71 | **True for servers without Search;** Search is optional ✔ | CDS:1 Table 9 |
| DLNA "bypasses a number of security headaches" | whealsie | **Misleading.** No storage credentials are needed, but only because UPnP has no access control: any device on the network can read the library. ✔ / DeviceProtection rarely implemented ✘ | UPnP MediaServer:4 |
| Windows Media Player / VLC work fine with miniDLNA | krvest and others | **True but not decisive:** browsing clients, not library imports | — |
| Expose MA players as DLNA renderers instead | busywait | **Valid; implemented** (`ma-dlna-renderer`, MA PR #3611) ✔ | §7 |

---

## 3. Protocol facts (UPnP ContentDirectory)

| Topic | Fact | Ref. |
|---|---|---|
| Actions | Browse, GetSearchCapabilities, GetSortCapabilities, GetSystemUpdateID **required**; **Search optional** ✔ | CDS:1 Table 9 |
| Tree | Containers can be "logical collections" or "arbitrary collections"; structure is up to the server ✔ | CDS:1 p. 7 |
| `refID` | A reference item has its own unique `@id`; its `@refID` "shall … always remain equal to the @id property of the item that is referenced". Many references can point to one master. Servers are *recommended* to use one master per content item and not to chain references ✔ | CDS:4 §5.2.21, B.1.3 |
| ID persistence | Preserving `@id` while the server is offline is **recommended** for all objects and **required** only for objects exposing change tracking (`upnp:objectUpdateID`/`containerUpdateID`). If persistence can't be ensured, the server must run the *Service Reset Procedure*, which changes `ServiceResetToken` (CDS:3+) ✔ | CDS:4 §5.2 (object @id), B.1.1, §5.3.7 |
| Counting | If `TotalMatches` can't be computed in time, the server returns `TotalMatches = 0` with the items found; with no items, error 720 ✔ | CDS:1 §2.7.4; CDS:4 Browse() |
| Paging | `RequestedCount = 0` "indicates request all entries". The specification doesn't explicitly allow returning fewer; real servers do (§4) ✔. Whether the (non-public) DLNA guidelines allow partial results is unverified ✘ | CDS:1/CDS:4 Browse() |
| Security | No authentication or encryption in UPnP AV; optional DeviceProtection exists ✔, rarely implemented ✘ | MediaServer:4 |
| Discovery | SSDP multicast (239.255.255.250:1900) ✔ | UPnP Device Architecture |

### 3.1 Change tracking: three levels

1. **`SystemUpdateID`** (required): one counter for the whole server, readable and sent as a notification. It increases on any change, telling a client *that* something changed but not *what*. ✔
2. **`ContainerUpdateIDs`** (optional): notifications of (container, update ID) pairs, sent in batches. It's "not a history list" and is cleared after each notification, so a client that was offline misses changes. ✔
3. **Track Changes Option** (CDS:3+, optional): a `LastChange` notification with an ordered log of `objAdd` / `objMod` / `objDel` / `stDone` events. Objects supporting it must keep their IDs while `ServiceResetToken` stays constant. ✔

**Consequence for MA:**
- `SystemUpdateID` unchanged on reconnect → nothing to do.
- Changed while subscribed to `ContainerUpdateIDs` → rescan only those containers.
- Otherwise → a full rescan.

For a browse/search-only provider this only matters for caching.

---

## 4. Server survey

No usage statistics for DLNA servers exist, so a true "top 10" can't be determined. The list below is a candidate set of widely used servers, plus MinimServer and JRiver because discussion #890 names them. The same data, one row per server and property with its evidence and source, is in [`data/server-survey.csv`](data/server-survey.csv).

| Server | Search | Text search | Counts (`TotalMatches`) | Stable IDs | Emits `refID` | Notes | Evidence |
|---|---|---|---|---|---|---|---|
| ReadyMedia (MiniDLNA) | yes | yes: `dc:title, dc:creator, dc:date, upnp:album, upnp:actor, upnp:artist, upnp:class, upnp:genre, @id, @parentID, @refID` | yes (`get_child_count`, `count(distinct DETAIL_ID)`) | across restarts yes; **a full database rebuild renumbers them** (sequential `parent$HEX` IDs via `get_next_available_id`) | yes | Search results de-duplicated per file | ✔ code |
| Gerbera | yes | yes (database-defined capabilities) | yes | database IDs; stable across restarts ✘ assumed | not found ✘ | Sends `ContainerUpdateIDs` and `SystemUpdateID` notifications | ✔ code |
| Jellyfin DLNA plugin (since Jellyfin 10.9) | yes | yes (broad: title, creator, artist, album, genre, class, @id, @refID, …) | yes | yes: item ID = MD5(type + path), stable across rescans; a moved or renamed file gets a new ID | **no** (`// refID?` comment only) | DLNA moved from core to a plugin in 10.9 | ✔ code |
| Kodi | **class only** (`SearchCapabilities = upnp:class`) | no; `audioItem` searches optionally filtered by exact genre/album/artist name | ✘ assumed yes | library DB IDs (`musicdb://songs/<id>`), stable until the library is rebuilt ✘ | yes (`m_ReferenceID`) | Can list all songs via class search | ✔ code |
| Universal Media Server | yes | yes: `upnp:class, dc:title, dc:creator, upnp:artist, upnp:album, upnp:genre` | ✘ not checked | yes: persisted in database table `MediaTableStoreIds` | not found ✘ | Global counter only, no `LastChange` found | ✔ code |
| Windows Media sharing | yes | ✘ | ✘ | ✘ not documented | ✘ | **Responses capped at 204,800 bytes** unless the client sets a compatibility flag | ✔ Microsoft spec MS-DLNHND |
| Twonky | reportedly yes | ◐ | ✘ | ✘ | ✘ | **Returns at most 500 items per request** (HA #113746) | ◐ docs / ✔ issue |
| MinimServer | yes (newer versions) | ◐ | ✘ | ✘ | ✘ | Highly flexible tag-based tree, so many paths to one album | ◐ docs |
| Plex (DLNA server) | ✘ | ✘ | ✘ | ✘ | ✘ | Closed source; no documentation found | ✘ |
| Emby | ✘ | ✘ | ✘ | ✘ | ✘ | Closed source (shares Jellyfin's ancestry) | ✘ |
| Serviio | ✘ | ✘ | ✘ | ✘ | ✘ | Closed source | ✘ |
| JRiver Media Center | ✘ | ✘ | ✘ | ✘ | ✘ | Closed source | ✘ |

**De-duplication rule (from the specification and the survey):** group by `refID`, else by `@id`. Then fall back to the `res` URL, and finally to (title, artist, album, duration), because some servers repeat items without `refID`.

---

## 5. Limitations and concerns for DLNA sources in MA

1. **No standard tree structure:** each server needs its own handling. ✔
2. **Search optional; capabilities vary** (`GetSearchCapabilities`). Without Search, there's no reliable way to list everything. ✔
3. **Duplicates** through multiple containers or reference items. ✔
4. **Unstable IDs:** only recommended to persist; resettable from CDS:3; ReadyMedia renumbers on rebuild. This breaks MA queue, favourite and playlist references. ✔
5. **Counts may be unknown** (`TotalMatches = 0`): paging must use `NumberReturned`. ✔
6. **Response caps** (Twonky 500 items, Windows 204,800 bytes): a single "all entries" request returns an incomplete list. ✔
7. **Change tracking only partly available** (see §3.1). ✔
8. **Thin, inconsistent metadata:** DIDL-Lite fields are mostly optional. ✔ MusicBrainz IDs, multiple artists and album artist are usually missing or handled inconsistently. ✘
9. **No authentication; local network only;** no remote access. ✔
10. **Discovery needs multicast** (host networking, same VLAN) or a manually entered URL. ✔
11. **Formats and seeking depend on the server** (protocol info, `DLNA.ORG_OP`; transcoding optional). ✘ untested against real servers
12. **Malformed DIDL from some devices** (WiiM/LinkPlay undeclared `song:` prefix). `DmsDevice` currently raises on it. ✔
13. **Shrinking ecosystem:** the DLNA organisation dissolved in 2017, with certification continued by SpireSpark; Jellyfin moved DLNA to a plugin. ReadyMedia, Gerbera, UMS and MinimServer are still maintained. ✔

---

## 6. async_upnp_client `DmsDevice`

### 6.1 What exists ✔
- Device types `MediaServer:1–4`; services ContentDirectory:1–4 and ConnectionManager.
- `async_browse(…, starting_index, requested_count, …)` → `BrowseResult(result, number_returned, total_matches, update_id)`.
- `async_browse_metadata`, `async_browse_direct_children` and `async_search_directory`: each fetches **one page**.
- `search_capabilities`, `sort_capabilities`, `has_search_directory`.
- `system_update_id`, `has_container_update_ids`, `container_update_ids` (notification-based).
- `get_absolute_url` (for cover art and stream URLs).
- In the same module: `DlnaOrgOp`, `DlnaOrgFlags` (protocol-info flags); `_cached_from_xml_string` with lenient DIDL parsing (catches `ParseError` / `DefusedXmlException`), currently used only by the renderer class `DmrDevice`.

### 6.2 Proposed upstream extensions (ranked)

| # | Extension | Why | Evidence |
|---|---|---|---|
| 1 | **Paging iterator** over browse and search: loop until done; use `NumberReturned`, not `TotalMatches`; handle 720 and capped responses | Every client needs it; fixes incomplete listings | HA #113746 (Twonky 500), MS-DLNHND (Windows cap) ✔ |
| 2 | **Lenient DIDL parsing in browse/search,** reusing the existing `ParseError`/`DefusedXmlException` handling, plus a hook for vendor quirks (e.g. WiiM `song:` prefix) | Robustness; parity with `DmrDevice` | upstream `dlna.py` (two direct `from_xml_string` calls in `DmsDevice`); fork `mastikamastika/fix-dlna-unbound-prefix` ✔ |
| 3 | **`ServiceResetToken`** property + `GetServiceResetToken`; **CDS `LastChange`** parsing (`objAdd/objMod/objDel/stDone`) into callbacks | Detect invalid IDs and exact changes | CDS:4 §5.3.7, Track Changes Option ✔ |
| 4 | **Resource-selection helper:** parse `res@protocolInfo` into MIME type + `DlnaOrgOp`/`DlnaOrgFlags`; pick the best resource for a list of acceptable MIME types; absolute URL | HA already has a simpler version (`_didl_to_play_media`); MA would write it again | HA `dlna_dms/dms.py` ✔ |
| 5 | **Search-criteria builder** limited to `search_capabilities` (`derivedfrom`, `contains`, escaping) | Same syntax for every client; HA passes raw strings | CDS:1 search grammar ✔ |
| 6 | **Duplicate-grouping key** (`refID` or `@id`) | Spec-defined; small | CDS:4 §5.2.21 ✔ |

**Backward compatibility:** HA depends on the library, so add new methods and properties rather than changing existing signatures.

### 6.3 What stays in MA
- Discovery orchestration and a manual-URL option.
- Device setup with MA's HTTP session.
- Wiring a notification server.
- DIDL → MA model mapping.
- Stream details.
- MA item IDs and fallback-by-search.
- De-duplication policy.
- Availability handling and one provider instance per server.

---

## 7. Existing work (as of 2026-10-09)

- **HA `dlna_dms`** (since 2022.3): browses and searches live, with no library import. It requests all children at once (`requested_count` default 0) and picks the first `res` with a MIME type. ✔
- **HA #113746** "Twonky library incomplete – 500 limit" (2024): exactly 500 artists shown. The code owner attributed it to Twonky not following the specification; the issue was closed as stale, unfixed. ✔
- **async_upnp_client:**
  - **Pull request #112** (2021) added `DmsDevice`; no other `DmsDevice` issues or pull requests. ✔
  - **Renderer-side pull requests** (not about media servers, listed for context):
    - **#327** (renderer transport commands wait up to the UPnP action response time of 30 s; no retry after a timeout): **merged** as `1b78c11`. ✔
    - **#328** (`async_wait_for_can_play` stops waiting once the renderer is `PLAYING`): open; the maintainer asked for tests on more devices. On three Philips Fidelio A5 renderers it changes nothing: they offer `Play` right after `SetAVTransportURI` and while playing, so the wait ends on its first check with and without the change. ✔
- **async_upnp_client forks:** all 48 checked with [`tools/fork_scan.py`](tools/fork_scan.py) (2026-10-09). Every branch was fetched: 132 branches with commits not in upstream, 621 such commits, of which 15 touch media-server or DIDL code (see [`data/fork-branches.csv`](data/fork-branches.csv) and [`data/fork-commits.csv`](data/fork-commits.csv)). ✔ Relevant results:
  - `chishm/dlna-dms-old` (2021): the original `DmsDevice` draft, superseded by #112; nothing unmerged of value.
  - `ssltg/fix/malformed-dlna-metadata`: lenient DIDL parsing, merged upstream, but only on the renderer path (see §6.2 #2).
  - `mastikamastika/fix-dlna-unbound-prefix` (2025-12): a WiiM/LinkPlay workaround patched into `DmsDevice`; no upstream pull request.
  - Unrelated to the media-server client: server-side eventing (PhracturedBlue), an OpenHome profile for MA's Linn player (MacTheFork), SSDP/IPv6/renderer fixes (others).
- **MA PR #3611** "Add DLNA Receiver plugin provider" (draft, open since 2026-04-07, updated 2026-09-08): exposes MA players as DLNA renderers, one per player. This is the renderer direction, like `ma-dlna-renderer`; docs pull request music-assistant.io #626. ✔
- **MA discussion #890** "DLNA Sources" (since 2022): no issue or pull request for a DMS *source* provider. ✔

---

## 8. Suggestions towards supporting playback in MA

*These are suggestions, not verified designs.*

### A. Recommended: a browse- and search-only DMS music provider
- **Features:** `ProviderFeature.BROWSE` and `SEARCH`, with no `LIBRARY_*`, so no full import is needed.
- **Instances and discovery:** one provider instance per server (UDN), discovered via SSDP for `MediaServer:1–4`, plus a manual description-URL option for Docker bridge networks or VLANs.
- **Item IDs:** `"<udn>/<objectID>"`, resolved with `async_browse_metadata`. If an ID no longer resolves, fall back to searching by title and artist. Watch `ServiceResetToken` where available.
- **Mapping:**
  - `object.item.audioItem.*` → Track, using `dc:title`, `upnp:artist` (roles), `upnp:album`, `upnp:originalTrackNumber`, `res@duration`;
  - `object.container.album.musicAlbum` → Album;
  - `object.container.person.musicArtist` → Artist;
  - other containers → browse folders;
  - cover art from `upnp:albumArtURI` via `get_absolute_url`.
- **Streaming:** select a `res` by protocol info (MIME type) and hand MA an HTTP stream. Allow seeking only if `DLNA.ORG_OP` allows range or time seeking, or if the server honours HTTP range requests.
- **Search:** build criteria only from `search_capabilities`, e.g. `upnp:class derivedfrom "object.item.audioItem" and (dc:title contains "…" or upnp:artist contains "…" or upnp:album contains "…")`. Without `has_search_directory`, browse only. For Kodi, use the class-only form with exact-name filters.
- **Robustness:**
  - page by `NumberReturned`;
  - de-duplicate (`refID`/`@id` → `res` URL → title, artist, album, duration);
  - parse DIDL leniently;
  - mark the server unavailable on an SSDP goodbye or a failed ping.
- **Risks:**
  - persistence of queues and favourites depends on ID stability;
  - library-based features (cross-provider matching, metadata enrichment, radio mode) will be limited ✘.

### B. Later, optional: library import
Only for servers that support Search and have stable IDs:
- list everything once via `upnp:class derivedfrom "object.item.audioItem"` with paging;
- skip rescans while `SystemUpdateID` (and `ServiceResetToken`) are unchanged;
- rescan per container when `ContainerUpdateIDs` notifications arrive.

Not a first step.

### C. Prerequisite upstream work
Contribute to async_upnp_client first: the paging iterator (also fixes HA #113746) and lenient DIDL parsing in `DmsDevice`, then the reset token, resource helper and search builder (§6.2).

### D. Interim options without a provider
- **Renderer direction:** a DLNA control app browses the DMS and plays on MA through `ma-dlna-renderer` or MA PR #3611. ✔ works with `ma-dlna-renderer`.
- **Via HA:** browse the DMS in HA's media browser (`dlna_dms`) and play on an MA `media_player` entity. ✘ *assumption, to test.*

### E. Test plan (per available server)
A probe script using `DmsDevice`:
1. `GetSearchCapabilities`, `GetSortCapabilities`, `has_search_directory`.
2. Browse the root and a large container with `RequestedCount=0`; compare `NumberReturned` with `TotalMatches` to detect caps.
3. Page through with fixed page sizes and check the total.
4. Search `upnp:class derivedfrom "object.item.audioItem"`: count, duplicates, `refID` presence.
5. Record IDs; restart the server; compare. Rescan or rebuild the library; compare again. Read `ServiceResetToken` if present.
6. Inspect the `res` elements: MIME types, `DLNA.ORG_OP`, HTTP range support.

---

## 9. Open questions and assumptions

- Behaviour of closed-source servers (Plex, Emby, Serviio, JRiver; Twonky and MinimServer beyond their docs). ✘
- Gerbera and Kodi ID stability across library rebuilds. ✘
- Whether the DLNA guidelines (not public) allow servers to return fewer items than requested for `RequestedCount=0`. ✘
- Whether UMS and Windows compute `TotalMatches` reliably. ✘
- The HA → MA media-source playback path (§8 D). ✘
- How rarely DeviceProtection is implemented in practice. ✘

---

## 10. Sources

**Specifications**
- UPnP ContentDirectory:1 (actions table, containers, Browse, TotalMatches, ContainerUpdateIDs): https://upnp.org/specs/av/UPnP-av-ContentDirectory-v1-Service.pdf
- UPnP ContentDirectory:4 (reference items/`refID`, ID persistence, `ServiceResetToken`, Track Changes/`LastChange`): https://upnp.org/specs/av/UPnP-av-ContentDirectory-v4-Service.pdf
- UPnP MediaServer:4 (DeviceProtection feature): https://upnp.org/specs/av/UPnP-av-MediaServer-v4-Device.pdf
- Microsoft MS-DLNHND, Browse/Search handling and the 204,800-byte cap: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dlnhnd/28e72c9b-225b-42ec-8891-bc7f7e220e8e

**Server source code and documentation**
- ReadyMedia `upnpsoap.c` (SearchCaps, `refID`, counts): https://sourceforge.net/p/minidlna/git/ci/1a9b32ee7a1c89e54e9f148199b73f9b33ad45ba/tree/upnpsoap.c (archived copy: [Software Heritage](https://archive.softwareheritage.org/swh:1:cnt:20f6b60342aff1d747da6653a61a7d335c48397f;origin=https://git.code.sf.net/p/minidlna/git;anchor=swh:1:rev:1a9b32ee7a1c89e54e9f148199b73f9b33ad45ba;path=/upnpsoap.c))
- ReadyMedia `scanner.c` (sequential object IDs): https://sourceforge.net/p/minidlna/git/ci/1a9b32ee7a1c89e54e9f148199b73f9b33ad45ba/tree/scanner.c (archived copy: [Software Heritage](https://archive.softwareheritage.org/swh:1:cnt:f240a2f6c97b595db863ae8ef8ba4badf4b2ecc4;origin=https://git.code.sf.net/p/minidlna/git;anchor=swh:1:rev:1a9b32ee7a1c89e54e9f148199b73f9b33ad45ba;path=/scanner.c))
- Gerbera `cont_dir_service.cc` (Search, TotalMatches, update IDs): https://github.com/gerbera/gerbera/blob/cce1d4025640941e543dd8f578f9158fabd90019/src/upnp/cont_dir_service.cc
- Jellyfin DLNA plugin `ControlHandler.cs` (Search, SearchCaps, TotalMatches): https://github.com/jellyfin/jellyfin-plugin-dlna/blob/21cd9fcee1b9bc017e766de4d10111a9deb71d5d/src/Jellyfin.Plugin.Dlna/ContentDirectory/ControlHandler.cs
- Jellyfin DLNA plugin `DidlBuilder.cs` (no `refID`): https://github.com/jellyfin/jellyfin-plugin-dlna/blob/21cd9fcee1b9bc017e766de4d10111a9deb71d5d/src/Jellyfin.Plugin.Dlna/Didl/DidlBuilder.cs
- Jellyfin `LibraryManager.cs` (ID = MD5(type + path)): https://github.com/jellyfin/jellyfin/blob/a45d1415d4da7c9b69d6e7a6895fc63d2d68e8f1/Emby.Server.Implementations/Library/LibraryManager.cs
- Jellyfin 10.9.0 release (DLNA moved to plugin): https://jellyfin.org/posts/jellyfin-release-10.9.0/
- Jellyfin DLNA docs: https://jellyfin.org/docs/general/post-install/networking/dlna/
- Kodi `UPnPServer.cpp` (class-only search): https://github.com/xbmc/xbmc/blob/0929e56b09c852df85669e5c421d2a75b84b2f4d/xbmc/network/upnp/UPnPServer.cpp (archived copy: [Software Heritage](https://archive.softwareheritage.org/swh:1:cnt:0dc2843dfb6cc21f856896546c04d754727ee862;origin=https://github.com/xbmc/xbmc;anchor=swh:1:rev:0929e56b09c852df85669e5c421d2a75b84b2f4d;path=/xbmc/network/upnp/UPnPServer.cpp))
- Kodi `UPnPInternal.cpp` (`refID`): https://github.com/xbmc/xbmc/blob/0929e56b09c852df85669e5c421d2a75b84b2f4d/xbmc/network/upnp/UPnPInternal.cpp (archived copy: [Software Heritage](https://archive.softwareheritage.org/swh:1:cnt:db3b5cbd84cf4524108512cddb5b3cbbae80dc65;origin=https://github.com/xbmc/xbmc;anchor=swh:1:rev:0929e56b09c852df85669e5c421d2a75b84b2f4d;path=/xbmc/network/upnp/UPnPInternal.cpp))
- UMS `UmsContentDirectoryService.java` (search capabilities, SystemUpdateID): https://github.com/UniversalMediaServer/UniversalMediaServer/blob/1b1cb16dce26a40da3774bf3bc31202a1049e25d/src/main/java/net/pms/network/mediaserver/jupnp/support/contentdirectory/UmsContentDirectoryService.java
- UMS `MediaStoreIds.java` (persistent IDs): https://github.com/UniversalMediaServer/UniversalMediaServer/blob/1b1cb16dce26a40da3774bf3bc31202a1049e25d/src/main/java/net/pms/store/MediaStoreIds.java
- MinimServer, UPnP and DLNA (no standard browse tree): https://minimserver.com/upnpav.html
- MinimServer, other features (UPnP search): https://minimserver.com/ug-other.html
- MinimServer features: https://minimserver.com/features.html
- Twonky docs: https://twonkydocs.atlassian.net/wiki/spaces/TS/overview
- Comparison of UPnP AV media servers (Wikipedia): https://en.wikipedia.org/wiki/Comparison_of_UPnP_AV_media_servers
- DLNA (Wikipedia; dissolution 2017, SpireSpark): https://en.wikipedia.org/wiki/Digital_Living_Network_Alliance

**Libraries, integrations, issues and pull requests**
- async_upnp_client `profiles/dlna.py` (`DmsDevice`, `DlnaOrgOp`, lenient parsing): https://github.com/StevenLooman/async_upnp_client/blob/1b78c11756bddfa0203d116f54251cdcf9967e13/async_upnp_client/profiles/dlna.py
- async_upnp_client PR #112 (DmsDevice added): https://github.com/StevenLooman/async_upnp_client/pull/112
- async_upnp_client PR #327 (renderer action timeout, merged): https://github.com/StevenLooman/async_upnp_client/pull/327
- async_upnp_client PR #328 (stop waiting for Play once PLAYING): https://github.com/StevenLooman/async_upnp_client/pull/328
- HA `dlna_dms` integration docs: https://www.home-assistant.io/integrations/dlna_dms/
- HA `dlna_dms/dms.py` (single-request browse, resource selection): https://github.com/home-assistant/core/blob/bc163ce1759e97c68eceff2870621ec521d6347d/homeassistant/components/dlna_dms/dms.py
- HA issue #113746 (Twonky 500 limit): https://github.com/home-assistant/core/issues/113746
- MA models `ProviderFeature` (BROWSE, SEARCH, LIBRARY_*): https://github.com/music-assistant/models/blob/0394e19239e1f1ce2a8de2faf62d42f11807815d/music_assistant_models/enums.py
- MA discussion #890 "DLNA Sources": https://github.com/orgs/music-assistant/discussions/890
- MA server PR #3611 "Add DLNA Receiver plugin provider": https://github.com/music-assistant/server/pull/3611
- MA docs PR #626 (DLNA Receiver plugin page): https://github.com/music-assistant/music-assistant.io/pull/626
- ma-dlna-renderer (HA add-on, MA players as DLNA renderers): https://github.com/peter--s/ma-dlna-renderer
- Fork branch with the WiiM/LinkPlay DIDL workaround: https://github.com/mastikamastika/async_upnp_client/commit/a406335
- Fork commit with the original DmsDevice draft: https://github.com/chishm/async_upnp_client/commit/507959104402

---

## 11. Data and tools

| Path | Content |
|---|---|
| [`data/server-survey.csv`](data/server-survey.csv) | Server survey (§4): one row per server and property, with evidence type (`verified-code`, `verified-spec`, `verified-issue`, `documented-vendor`, `documented-secondary`, `unverified`) and pinned source |
| [`data/fork-branches.csv`](data/fork-branches.csv) | Every async_upnp_client fork branch with commits not in upstream, and how many of them touch media-server/DIDL code |
| [`data/fork-commits.csv`](data/fork-commits.csv) | The commits not in upstream whose changes touch media-server/DIDL code, with the branches containing them |
| [`tools/fork_scan.py`](tools/fork_scan.py) | Produces both fork CSV files: `python3 tools/fork_scan.py data` (needs git and network access) |

Corrections and measurements from other servers are welcome as issues or pull requests; please state how a value was verified.

## License

Text and data: [CC BY 4.0](LICENSE-docs). Code in `tools/`: [MIT](LICENSE). Quoted specification passages remain the property of their owners and are quoted for reference only; the specifications themselves are linked, not redistributed.
