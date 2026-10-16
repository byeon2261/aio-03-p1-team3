"""demo1의 카카오 지도 데모를 Streamlit으로 실행한다."""

import hashlib
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from listings import SEOUL_STATION, price_text, search_listings


load_dotenv(Path(__file__).with_name(".env"))


def configured_api_key() -> str:
    """환경 변수 또는 Streamlit secrets에서 JavaScript 키를 읽는다."""
    if value := os.getenv("KAKAO_JAVASCRIPT_KEY", "").strip():
        return value
    try:
        return str(st.secrets.get("KAKAO_JAVASCRIPT_KEY", "")).strip()
    except FileNotFoundError:
        return ""


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
  let state = parentElement.__demoStPostcode;
  if (!state) {
    state = {disposed: false};
    parentElement.__demoStPostcode = state;
    const status = parentElement.querySelector(".demo-st-postcode-status");
    const container = parentElement.querySelector(".demo-st-postcode");
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
    parentElement.querySelector(".demo-st-postcode").replaceChildren();
    delete parentElement.__demoStPostcode;
  };
}
"""

_POSTCODE = st.components.v2.component(
    "demo_st_postcode",
    html="""
    <p class="demo-st-postcode-status" role="status">주소 검색창을 불러오는 중입니다.</p>
    <div class="demo-st-postcode" aria-label="카카오 주소 검색"></div>
    """,
    js=POSTCODE_JS,
    isolate_styles=False,
)


@st.dialog("주소 검색")
def address_search_dialog():
    result = _POSTCODE(key="postcode_picker", on_selected_change=lambda: None, height=510)
    if result.selected:
        selected = result.selected
        st.session_state.map_command = {
            "id": st.session_state.map_command["id"] + 1,
            "type": "address_search",
            "query": selected["query"],
            "address": selected,
        }
        st.rerun()


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
  let state = parentElement.__demoStMap;
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
    parentElement.__demoStMap = state;
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
        const road = document.createElement("p");
        const parcel = document.createElement("p");
        title.textContent = "[더미] " + listing.title;
        details.textContent = listing.price + " · " + Math.round(listing.distance_m) + "m";
        road.textContent = "도로명: " + listing.road_address;
        parcel.textContent = "지번: " + listing.parcel_address;
        content.append(title, road, parcel, details);
        state.infoWindow.setContent(content);
        state.infoWindow.open(state.map, marker);
        state.selectedListingId = listing.id;
        state.status = "선택한 매물 주소: " + listing.address;
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
      const container = parentElement.querySelector(".demo-st-kakao-map");
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
    delete parentElement.__demoStMap;
  };
}
"""

_KAKAO_MAP = st.components.v2.component(
    "demo_st_kakao_map",
    html='<div class="demo-st-kakao-map" role="region" aria-label="드래그와 확대가 가능한 카카오 지도"></div>',
    css="""
    .demo-st-kakao-map {
      width: 100%;
      height: 580px;
      border-radius: 12px;
      overflow: hidden;
      background: var(--st-secondary-background-color);
    }
    """,
    js=MAP_JS,
    # 카카오 SDK가 document에 삽입하는 지도 스타일을 적용한다.
    isolate_styles=False,
)


def update_search_origin(key: str):
    view = st.session_state.get(key, {}).get("view") or {}
    if "searchOrigin" in view:
        st.session_state.search_origin = view["searchOrigin"]
    if "selectedListingId" in view:
        st.session_state.selected_listing_id = view["selectedListingId"]


def kakao_map(api_key: str, command: dict, search: dict, *, key: str):
    previous = st.session_state.get(key, {}).get("view")
    return _KAKAO_MAP(
        key=key,
        data={"apiKey": api_key, "command": command, "view": previous, "search": search},
        default={"view": None},
        on_view_change=lambda: update_search_origin(key),
        height=580,
    )


def coordinate_text(point: dict | None) -> str:
    if not point:
        return "—"
    return f"{point['latitude']:.6f}, {point['longitude']:.6f}"


def display_listing_address(listing: dict):
    st.caption("도로명주소")
    st.text(listing["road_address"])
    st.caption("지번주소")
    st.text(listing["parcel_address"])
    if listing.get("building_name"):
        st.caption("건물명")
        st.text(listing["building_name"])
    st.caption(f"우편번호 {listing['postal_code']} · 건물 대표 좌표 기준")


st.set_page_config(page_title="동네 지도 탐색", page_icon=":material/map:", layout="wide")
st.session_state.setdefault("map_command", {"id": 0, "type": "none"})
st.session_state.setdefault("search_origin", SEOUL_STATION.copy())
st.session_state.setdefault("selected_listing_id", None)

st.caption("MAP EXPLORER")
st.title("동네 지도 탐색")
st.caption("지도를 드래그하거나 확대해 보세요. 지도 이동이 끝나면 현재 화면의 좌표 범위가 업데이트됩니다.")
st.caption("서울역 주변 실제 주소·건물 대표 좌표를 사용하는 샘플 9개입니다. 가격·면적·층수·매물 조건은 가상입니다.")

with st.expander("카카오 지도 설정", expanded=not bool(configured_api_key())):
    api_key = st.text_input(
        "카카오 JavaScript 키",
        value=configured_api_key(),
        type="password",
        key="kakao_javascript_key",
        help="환경 변수 또는 Streamlit secrets의 KAKAO_JAVASCRIPT_KEY로도 설정할 수 있습니다.",
    ).strip()
    st.caption("카카오 개발자 콘솔의 Web 도메인에 접속 주소(예: http://localhost:8501)를 등록해 주세요.")

map_column, coordinate_column = st.columns([3, 1])
view = None

with map_column:
    with st.container(border=True):
        if st.button("주소 검색", icon=":material/location_on:", type="primary", disabled=not api_key):
            address_search_dialog()
        st.caption("카카오 주소 검색창에서 도로명·지번·건물명을 검색하고 주소를 선택해 주세요.")

        if st.button("서울역 더미 매물 보기", icon=":material/home_work:", key="demo_origin"):
            st.session_state.search_origin = SEOUL_STATION.copy()
            st.session_state.selected_listing_id = None
            st.session_state.map_command = {
                "id": st.session_state.map_command["id"] + 1,
                "type": "set_origin",
                "origin": SEOUL_STATION.copy(),
            }

        radius_m = st.segmented_control(
            "검색 반경", options=[300, 500, 1000], default=300,
            format_func=lambda value: "1km" if value == 1000 else f"{value}m",
            required=True, key="radius_m",
        )

        with st.form("station_search"):
            input_column, button_column = st.columns([4, 1], vertical_alignment="bottom")
            with input_column:
                query = st.text_input(
                    "검색할 역 이름", placeholder="역 이름을 입력하세요 (예: 강남역)", key="station_query"
                )
            with button_column:
                search = st.form_submit_button("역 검색", type="primary", disabled=not api_key)
        if search:
            if query.strip():
                st.session_state.map_command = {
                    "id": st.session_state.map_command["id"] + 1,
                    "type": "search",
                    "query": query.strip(),
                }
            else:
                st.warning("검색할 역 이름을 입력해 주세요.")

        if st.button("서울 중심으로", icon=":material/my_location:", key="reset_map", disabled=not api_key):
            st.session_state.search_origin = None
            st.session_state.selected_listing_id = None
            st.session_state.map_command = {
                "id": st.session_state.map_command["id"] + 1,
                "type": "reset",
            }

        origin = st.session_state.search_origin
        nearby_listings = search_listings(origin, radius_m)
        if st.session_state.selected_listing_id not in {listing["id"] for listing in nearby_listings}:
            st.session_state.selected_listing_id = None
        search_payload = {
            "origin": origin,
            "radiusM": radius_m,
            "listings": [{**listing, "price": price_text(listing)} for listing in nearby_listings],
        }

        if api_key:
            # 키 변경 시 이전 지도 인스턴스와 상태를 재사용하지 않는다.
            map_key = "kakao_map_" + hashlib.sha256(api_key.encode()).hexdigest()[:12]
            result = kakao_map(api_key, st.session_state.map_command, search_payload, key=map_key)
            view = result.view
            if view and view.get("error"):
                st.error(view["status"])
            else:
                st.caption(view["status"] if view else "지도를 불러오는 중입니다.")
        else:
            st.info("카카오 JavaScript 키를 입력하면 지도가 표시됩니다.")

    st.subheader(f"주변 매물 {len(nearby_listings)}개")
    if origin:
        st.caption(f"기준: {origin['label']} · 반경 {radius_m:,}m · 직선거리 가까운 순")
        st.caption("반경을 넓히면 안쪽 매물도 포함됩니다. 지도 이동은 검색 기준점을 바꾸지 않습니다.")
        if not nearby_listings:
            st.info("선택한 반경 안에 더미 매물이 없습니다. 반경을 넓히거나 서울역 더미 매물 보기를 눌러 보세요.")
    else:
        st.info("주소나 역을 검색하거나 서울역 더미 매물 보기를 눌러 검색 기준을 선택해 주세요.")
    for index, listing in enumerate(nearby_listings, 1):
        with st.expander(f"{index}. {listing['title']} · {listing['distance_m']:.0f}m"):
            st.text(f"{listing['lease_type']} · {price_text(listing)}")
            st.caption(f"{listing['property_type']} · {listing['area_m2']}㎡ · {listing['floor']}층")
            display_listing_address(listing)
            st.caption("주소는 실제 위치이며, 표시된 매물 조건은 테스트용입니다.")
            if st.button("매물 선택 · 지도에서 보기", key=f"focus_{listing['id']}"):
                st.session_state.selected_listing_id = listing["id"]
                st.session_state.map_command = {
                    "id": st.session_state.map_command["id"] + 1,
                    "type": "focus_listing",
                    "listingId": listing["id"],
                }
                st.rerun()

with coordinate_column:
    selected_listing = next(
        (listing for listing in nearby_listings if listing["id"] == st.session_state.selected_listing_id), None
    )
    if selected_listing:
        with st.container(border=True):
            st.subheader("선택한 매물 주소")
            st.text(selected_listing["title"])
            display_listing_address(selected_listing)
            st.text(price_text(selected_listing))
            st.caption("실제 주소를 사용하는 가상 매물입니다.")
            st.link_button("주소 정보 출처", selected_listing["address_source_url"])

    with st.container(border=True):
        st.subheader("매물 검색 기준")
        st.text(origin["label"] if origin else "기준점 없음")
        st.metric("검색 결과", f"{len(nearby_listings)}개")
        st.caption(f"반경 {radius_m:,}m · 가상 매물 총 9개")

    if view and view.get("selectedAddress"):
        with st.container(border=True):
            st.subheader("검색한 주소")
            selected_address = view["selectedAddress"]
            if selected_address.get("zonecode"):
                st.caption("우편번호")
                st.text(selected_address["zonecode"])
            if selected_address.get("roadAddress"):
                st.caption("도로명주소")
                st.text(selected_address["roadAddress"])
            if selected_address.get("parcelAddress"):
                st.caption("지번주소")
                st.text(selected_address["parcelAddress"])
            if selected_address.get("buildingName"):
                st.caption("건물명")
                st.text(selected_address["buildingName"])

    with st.container(border=True):
        st.subheader("현재 지도 영역")
        st.caption("아래 좌표 범위를 매물 검색 API에 전달하면 현재 화면 안의 매물을 조회할 수 있습니다.")
        for name, label in (
            ("center", "지도 중심 (위도, 경도)"),
            ("southwest", "남서쪽 (위도, 경도)"),
            ("northeast", "북동쪽 (위도, 경도)"),
        ):
            st.caption(label)
            st.code(coordinate_text(view.get(name) if view else None), language=None)
