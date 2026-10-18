"""F13 지도 탐색 부품: 카카오 지도·카카오 주소 검색 창(Streamlit Custom Components v2).

변건형님 지도 데모(옛 demo_st/main.py)의 JavaScript를 그대로 옮기고, 가상 매물 팝업은 동 단위 지역만 보여 주도록 바꿨다.
import 시 st 함수를 부르지 않는다(컴포넌트는 처음 쓸 때 만든다).
"""

from __future__ import annotations

import hashlib

import streamlit as st

from features.map import logic

POSTCODE_JS = """
let postcodePromise;

function loadPostcode() {
  const existing = window.kakao?.Postcode || window.daum?.Postcode;
  if (existing) return Promise.resolve(existing);
  if (!postcodePromise) {
    postcodePromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const timer = setTimeout(() => reject(new Error("주소 검색창 로딩 시간이 초과되었습니다.")), 20000);
      script.src = "https://t1.kakaocdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js";
      script.onload = () => {
        clearTimeout(timer);
        const Postcode = window.kakao?.Postcode || window.daum?.Postcode;
        if (Postcode) resolve(Postcode);
        else reject(new Error("카카오 주소 검색 서비스를 불러오지 못했습니다."));
      };
      script.onerror = () => {
        clearTimeout(timer);
        reject(new Error("주소 검색 서비스를 불러오지 못했습니다. 네트워크를 확인해 주세요."));
      };
      document.head.appendChild(script);
    }).catch(error => {
      postcodePromise = null;
      throw error;
    });
  }
  return postcodePromise;
}

export default function(component) {
  const {parentElement, setTriggerValue} = component;
  let state = parentElement.__mapExplorerPostcode;
  if (!state) {
    state = {disposed: false};
    parentElement.__mapExplorerPostcode = state;
    const status = parentElement.querySelector(".map-explorer-postcode-status");
    const container = parentElement.querySelector(".map-explorer-postcode");
    loadPostcode().then(Postcode => {
      if (state.disposed) return;
      status.textContent = "도로명, 지번 또는 건물명을 검색한 뒤 주소를 선택해 주세요.";
      state.picker = new Postcode({
        width: "100%", height: 450,
        oncomplete: selected => {
          if (state.disposed) return;
          const query = selected.userSelectedType === "R"
            ? selected.roadAddress || selected.address
            : selected.jibunAddress || selected.address;
          if (!query) return;
          state.emit("selected", {
            query,
            roadAddress: selected.roadAddress || "",
            parcelAddress: selected.jibunAddress || "",
            zonecode: selected.zonecode || "",
            buildingName: selected.buildingName || "",
          });
        },
      });
      state.picker.embed(container);
    }).catch(error => {
      if (!state.disposed) status.textContent = error.message + " 검색창을 닫고 다시 열어 주세요.";
    });
  }
  state.emit = setTriggerValue;
  return () => {
    state.disposed = true;
    parentElement.querySelector(".map-explorer-postcode").replaceChildren();
    delete parentElement.__mapExplorerPostcode;
  };
}
"""

MAP_JS = """
let sdkPromise;
let sdkKey;

function loadSdk(apiKey) {
  if (sdkPromise) {
    if (sdkKey !== apiKey) {
      return Promise.reject(new Error("키를 변경했다면 페이지를 새로고침해 주세요."));
    }
    return sdkPromise;
  }
  sdkKey = apiKey;
  sdkPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    const timer = setTimeout(() => {
      reject(new Error("지도 로딩 시간이 초과되었습니다. 네트워크와 앱 키를 확인해 주세요."));
    }, 20000);
    script.src = "https://dapi.kakao.com/v2/maps/sdk.js?" +
      new URLSearchParams({appkey: apiKey, autoload: "false", libraries: "services"});
    script.onload = () => {
      if (!window.kakao?.maps) {
        clearTimeout(timer);
        reject(new Error("카카오 지도 SDK를 불러오지 못했습니다."));
        return;
      }
      window.kakao.maps.load(() => {
        clearTimeout(timer);
        resolve(window.kakao.maps);
      });
    };
    script.onerror = () => {
      clearTimeout(timer);
      reject(new Error("지도를 불러오지 못했습니다. JavaScript 키와 Web 도메인 등록을 확인해 주세요."));
    };
    document.head.appendChild(script);
  });
  return sdkPromise;
}

export default function(component) {
  const {parentElement, data, setStateValue} = component;
  let state = parentElement.__mapExplorerMap;
  if (!state) {
    state = {
      map: null, marker: null, started: false, disposed: false,
      lastCommand: null, request: 0, lastView: "",
      selectedAddress: null,
      selectedListingId: data.view?.selectedListingId ?? null,
      searchOrigin: data.search.origin,
      listingMarkers: [], listingListeners: [], circle: null,
      infoWindow: null, lastSearch: "",
      status: "지도를 드래그해 주변을 탐색해 보세요.",
    };
    parentElement.__mapExplorerMap = state;
  }
  state.data = data;
  state.emit = setStateValue;

  function publish(error = false) {
    if (state.disposed) return;
    const view = {
      status: state.status, error,
      selectedAddress: state.selectedAddress,
      searchOrigin: state.searchOrigin,
      selectedListingId: state.selectedListingId,
    };
    if (state.map) {
      const point = p => ({latitude: p.getLat(), longitude: p.getLng()});
      const bounds = state.map.getBounds();
      view.center = point(state.map.getCenter());
      view.southwest = point(bounds.getSouthWest());
      view.northeast = point(bounds.getNorthEast());
      view.level = state.map.getLevel();
    }
    const serialized = JSON.stringify(view);
    if (serialized !== state.lastView) {
      state.lastView = serialized;
      state.emit("view", view);
    }
  }

  function showAddress(address) {
    const maps = window.kakao.maps;
    const position = new maps.LatLng(address.latitude, address.longitude);
    state.marker?.setMap(null);
    state.marker = new maps.Marker({position, map: state.map});
    state.map.setLevel(3);
    state.map.setCenter(position);
    state.selectedAddress = address;
    state.selectedListingId = null;
    state.searchOrigin = {
      label: address.label, latitude: address.latitude, longitude: address.longitude,
    };
    state.status = `"${address.label}" 위치로 이동했습니다.`;
    publish();
  }

  function clearListings() {
    state.infoWindow?.close();
    for (const [marker, listener] of state.listingListeners) {
      window.kakao.maps.event.removeListener(marker, "click", listener);
    }
    state.listingListeners = [];
    for (const marker of state.listingMarkers) marker.setMap(null);
    state.listingMarkers = [];
    state.circle?.setMap(null);
    state.circle = null;
  }

  function syncListings() {
    if (!state.map) return;
    const search = state.data.search;
    const serialized = JSON.stringify(search);
    if (serialized === state.lastSearch) return;
    const previousSearch = state.lastSearch ? JSON.parse(state.lastSearch) : null;
    state.lastSearch = serialized;
    clearListings();
    if (state.selectedListingId && !search.listings.some(item => item.id === state.selectedListingId)) {
      state.selectedListingId = null;
      publish();
    }
    if (!search.origin) return;
    const maps = window.kakao.maps;
    const position = new maps.LatLng(search.origin.latitude, search.origin.longitude);
    state.marker?.setMap(null);
    state.marker = new maps.Marker({position, map: state.map, title: "검색 기준: " + search.origin.label, zIndex: 10});
    state.circle = new maps.Circle({
      center: position, radius: search.radiusM,
      strokeWeight: 2, strokeColor: "#2563eb", strokeOpacity: 0.8,
      fillColor: "#93c5fd", fillOpacity: 0.15,
    });
    state.circle.setMap(state.map);
    state.infoWindow = new maps.InfoWindow({removable: true});
    for (const listing of search.listings) {
      const marker = new maps.Marker({
        position: new maps.LatLng(listing.latitude, listing.longitude),
        map: state.map, title: listing.title + " · " + Math.round(listing.distance_m) + "m",
      });
      marker.__listingId = listing.id;
      const listener = () => {
        const content = document.createElement("div");
        const title = document.createElement("strong");
        const details = document.createElement("p");
        content.style.padding = "4px 8px";
        title.textContent = (listing.road_address ? "[실제 주소] " : "[가상] ") + listing.title;
        details.textContent = listing.price + " · " + Math.round(listing.distance_m) + "m";
        content.append(title);
        if (listing.road_address) {
          const road = document.createElement("p");
          const parcel = document.createElement("p");
          road.textContent = "도로명: " + listing.road_address;
          parcel.textContent = "지번: " + listing.parcel_address;
          content.append(road, parcel);
        } else {
          const area = document.createElement("p");
          area.textContent = listing.area_name + " 일대(가상 위치)";
          content.append(area);
        }
        content.append(details);
        state.infoWindow.setContent(content);
        state.infoWindow.open(state.map, marker);
        state.selectedListingId = listing.id;
        state.status = `"${listing.title}"을(를) 선택했습니다.`;
        publish();
      };
      maps.event.addListener(marker, "click", listener);
      state.listingListeners.push([marker, listener]);
      state.listingMarkers.push(marker);
    }
    // 지도 드래그나 상태 갱신에는 확대 수준을 바꾸지 않는다.
    if (!previousSearch || previousSearch.radiusM !== search.radiusM ||
        JSON.stringify(previousSearch.origin) !== JSON.stringify(search.origin)) {
      state.map.setBounds(state.circle.getBounds(), 36);
    }
  }

  function applyCommand() {
    const command = state.data.command;
    if (!state.map || !command || command.id === state.lastCommand) return;
    state.lastCommand = command.id;
    const request = ++state.request;
    const maps = window.kakao.maps;
    if (command.type === "reset") {
      clearListings();
      state.marker?.setMap(null);
      state.marker = null;
      state.selectedAddress = null;
      state.selectedListingId = null;
      state.searchOrigin = null;
      state.map.setLevel(5);
      state.map.setCenter(new maps.LatLng(37.5665, 126.978));
      state.status = "서울 중심으로 이동했습니다.";
      publish();
    } else if (command.type === "set_origin") {
      state.selectedAddress = null;
      state.selectedListingId = null;
      state.searchOrigin = command.origin;
      state.lastSearch = "";
      state.map.setCenter(new maps.LatLng(command.origin.latitude, command.origin.longitude));
      state.status = "서울역 데모 기준점으로 이동했습니다.";
      publish();
    } else if (command.type === "focus_listing") {
      const listing = state.data.search.listings.find(item => item.id === command.listingId);
      if (listing) {
        state.map.panTo(new maps.LatLng(listing.latitude, listing.longitude));
        state.selectedListingId = listing.id;
        state.status = `"${listing.title}" 위치로 이동했습니다.`;
        const entry = state.listingListeners.find(([marker]) => marker.__listingId === listing.id);
        if (entry) entry[1]();
        publish();
      }
    } else if (command.type === "address_search") {
      state.status = `"${command.query}" 위치를 확인하고 있습니다.`;
      publish();
      state.geocoder.addressSearch(command.query, (results, status) => {
        if (state.disposed || request !== state.request) return;
        if (status !== maps.services.Status.OK || !results.length) {
          const noResults = status === maps.services.Status.ZERO_RESULT ||
            (status === maps.services.Status.OK && !results.length);
          state.status = noResults
            ? `"${command.query}" 주소의 지도 좌표를 찾지 못했습니다. 다른 주소를 선택해 주세요.`
            : "주소 좌표 변환에 실패했습니다. 카카오 앱 설정과 네트워크를 확인해 주세요.";
          publish(!noResults);
          return;
        }
        const result = results[0];
        const selected = command.address || {};
        showAddress({
          label: command.query,
          roadAddress: selected.roadAddress || result.road_address?.address_name || "",
          parcelAddress: selected.parcelAddress || result.address?.address_name || "",
          zonecode: selected.zonecode || "",
          buildingName: selected.buildingName || "",
          latitude: Number(result.y),
          longitude: Number(result.x),
        });
      });
    } else if (command.type === "search") {
      state.status = `"${command.query}" 역을 검색하고 있습니다.`;
      publish();
      state.places.keywordSearch(command.query, (results, status) => {
        if (state.disposed || request !== state.request) return;
        if (status !== maps.services.Status.OK) {
          state.status = status === maps.services.Status.ZERO_RESULT
            ? `"${command.query}" 검색 결과가 없습니다.`
            : "역 검색에 실패했습니다. 카카오 앱 설정과 네트워크를 확인해 주세요.";
          publish(status !== maps.services.Status.ZERO_RESULT);
          return;
        }
        const station = results.find(place => place.category_group_code === "SW8");
        if (!station) {
          state.status = `"${command.query}"에 해당하는 역을 찾지 못했습니다.`;
          publish();
          return;
        }
        const position = new maps.LatLng(Number(station.y), Number(station.x));
        state.marker?.setMap(null);
        state.marker = new maps.Marker({position, map: state.map});
        state.selectedAddress = null;
        state.selectedListingId = null;
        state.searchOrigin = {
          label: station.place_name, latitude: Number(station.y), longitude: Number(station.x),
        };
        state.map.setLevel(4);
        state.map.setCenter(position);
        state.status = `"${station.place_name}" 위치로 이동했습니다.`;
        publish();
      }, {category_group_code: "SW8"});
    }
  }

  if (state.map) {
    applyCommand();
    syncListings();
  } else if (!state.started) {
    state.started = true;
    loadSdk(data.apiKey).then(maps => {
      if (state.disposed) return;
      const previous = state.data.view;
      const center = previous?.center ?? state.data.search.origin ?? {latitude: 37.5665, longitude: 126.978};
      const container = parentElement.querySelector(".map-explorer-kakao-map");
      state.map = new maps.Map(container, {
        center: new maps.LatLng(center.latitude, center.longitude),
        level: previous?.level ?? 5,
      });
      state.places = new maps.services.Places();
      state.geocoder = new maps.services.Geocoder();
      state.idleHandler = () => publish();
      maps.event.addListener(state.map, "idle", state.idleHandler);
      state.observer = new ResizeObserver(() => {
        const center = state.map.getCenter();
        state.map.relayout();
        state.map.setCenter(center);
        publish();
      });
      state.observer.observe(container);
      syncListings();
      applyCommand();
      publish();
    }).catch(error => {
      state.status = error.message;
      publish(true);
    });
  }

  return () => {
    state.disposed = true;
    state.request++;
    state.observer?.disconnect();
    clearListings();
    state.marker?.setMap(null);
    if (state.map) {
      window.kakao.maps.event.removeListener(state.map, "idle", state.idleHandler);
    }
    delete parentElement.__mapExplorerMap;
  };
}
"""

MAP_CSS = """
.map-explorer-kakao-map {
  width: 100%;
  height: 580px;
  border-radius: 12px;
  overflow: hidden;
  background: var(--st-secondary-background-color);
}
"""

_components: dict[str, object] = {}


def _postcode():
    if "postcode" not in _components:
        _components["postcode"] = st.components.v2.component(
            "map_explorer_postcode",
            html="""
            <p class="map-explorer-postcode-status" role="status">주소 검색창을 불러오는 중입니다.</p>
            <div class="map-explorer-postcode" aria-label="카카오 주소 검색"></div>
            """,
            js=POSTCODE_JS,
            isolate_styles=False,
        )
    return _components["postcode"]


def _kakao_map():
    if "map" not in _components:
        _components["map"] = st.components.v2.component(
            "map_explorer_kakao_map",
            html='<div class="map-explorer-kakao-map" role="region" aria-label="드래그와 확대가 가능한 카카오 지도"></div>',
            css=MAP_CSS,
            js=MAP_JS,
            # 카카오 SDK가 document에 삽입하는 지도 스타일을 적용한다.
            isolate_styles=False,
        )
    return _components["map"]


def open_address_search() -> None:
    """주소 검색 창을 띄우고, 주소를 고르면 지도에 주소 검색 명령을 보낸다."""

    @st.dialog("주소 검색")
    def _dialog() -> None:
        result = _postcode()(key="map_postcode_picker", on_selected_change=lambda: None, height=510)
        selected = getattr(result, "selected", None)
        if selected:
            st.session_state[logic.COMMAND] = logic.next_command(
                st.session_state.get(logic.COMMAND), "address_search",
                query=selected["query"], address=selected,
            )
            st.rerun()

    _dialog()


def _sync_from_map(key: str) -> None:
    view = (st.session_state.get(key) or {}).get("view") or {}
    if "searchOrigin" in view:
        st.session_state[logic.ORIGIN] = view["searchOrigin"]
    if "selectedListingId" in view:
        st.session_state[logic.SELECTED] = view["selectedListingId"]


def kakao_map(api_key: str, command: dict, search: dict):
    """지도를 그리고 지도 상태(view)를 돌려준다. 키가 바뀌면 지도를 새로 만든다."""
    key = "map_kakao_" + hashlib.sha256(api_key.encode()).hexdigest()[:12]
    previous = (st.session_state.get(key) or {}).get("view")
    return _kakao_map()(
        key=key,
        data={"apiKey": api_key, "command": command, "view": previous, "search": search},
        default={"view": None},
        on_view_change=lambda: _sync_from_map(key),
        height=580,
    )
