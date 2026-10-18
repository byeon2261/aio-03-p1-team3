"""F13 지도 부품: 매물 핀 지도·카카오 주소 검색 창(Streamlit Custom Components v2).

주소 검색 창과 SDK 로딩은 변건형님 지도 데모(demo_st/main.py)의 JavaScript를 옮겼다.
import 시 st 함수를 부르지 않는다. 컴포넌트는 쓸 때마다 선언한다(같은 이름은 덮어쓰고, 모듈에 캐시하면
Streamlit 런타임이 바뀔 때 등록이 사라져 'is not registered' 오류가 난다).
"""

from __future__ import annotations

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

PINS_JS = """
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
    if (window.kakao?.maps?.services) {
      resolve(window.kakao.maps);
      return;
    }
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
  const {parentElement, data, setStateValue, setTriggerValue} = component;
  let state = parentElement.__mapPins;
  if (!state) {
    state = {
      map: null, started: false, disposed: false, markers: [], overlays: [], listeners: [],
      card: null, temp: null, lastPins: "", lastGeocode: null, pinIndex: {}, activeId: null,
      panelOpen: true, lastPanel: "",
    };
    parentElement.__mapPins = state;
  }
  state.data = data;
  state.setState = setStateValue;
  state.trigger = setTriggerValue;
  const statusEl = parentElement.querySelector(".map-pins-status");

  function setStatus(text, error = false) {
    statusEl.textContent = text || "";
    statusEl.classList.toggle("map-pins-error", error);
  }

  function closeCard() {
    state.card?.setMap(null);
    state.card = null;
    setActive(null);
  }

  function setActive(id) {
    state.activeId = id;
    for (const item of parentElement.querySelectorAll(".map-list-item")) {
      const on = item.dataset.id === id;
      item.classList.toggle("is-active", on);
      item.setAttribute("aria-current", on ? "true" : "false");
      if (on) item.scrollIntoView({block: "nearest", behavior: "smooth"});
    }
  }

  function focusPin(id) {
    const entry = state.pinIndex[id];
    if (!entry || !state.map) return;
    if (state.map.getLevel() > 4) state.map.setLevel(4);
    openCard(entry.pin, entry.position);
  }

  function buildCard(pin) {
    const card = document.createElement("div");
    card.className = "map-pin-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", pin.label + " 정보");
    for (const type of ["mousedown", "touchstart", "dblclick", "wheel"]) {
      card.addEventListener(type, event => event.stopPropagation());
    }

    const head = document.createElement("div");
    head.className = "map-pin-card__head";
    const badge = document.createElement("span");
    badge.className = "map-pin-card__badge";
    badge.textContent = pin.label;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "map-pin-card__close";
    close.setAttribute("aria-label", "닫기");
    close.textContent = "×";
    close.addEventListener("click", event => {
      event.stopPropagation();
      closeCard();
    });
    head.append(badge, close);
    card.append(head);

    if (pin.detail) {
      const address = document.createElement("p");
      address.className = "map-pin-card__address";
      address.textContent = pin.detail;
      card.append(address);
    }
    if ((pin.rows || []).length) {
      const list = document.createElement("dl");
      list.className = "map-pin-card__rows";
      for (const row of pin.rows) {
        const term = document.createElement("dt");
        term.textContent = row.label;
        const value = document.createElement("dd");
        value.textContent = row.value;
        if (row.muted) value.classList.add("is-muted");
        list.append(term, value);
      }
      card.append(list);
    }
    if (pin.note) {
      const note = document.createElement("p");
      note.className = "map-pin-card__note";
      note.textContent = pin.note;
      card.append(note);
    }
    if (pin.link) {
      const link = document.createElement("a");
      link.className = "map-pin-card__link";
      link.href = "#";
      link.setAttribute("role", "button");
      link.textContent = "매물 상세 보기";
      link.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        state.trigger("open", pin.id);
      });
      card.append(link);
    }
    return card;
  }

  // 카드 아래에 투명한 여백(padding)을 둬서 핀과 이름표를 가리지 않게 한다.
  // margin은 오버레이 크기 계산에 들어가지 않으므로 padding을 쓴다.
  function wrapCard(card) {
    const wrap = document.createElement("div");
    wrap.className = "map-pin-card-wrap";
    wrap.append(card);
    return wrap;
  }

  function openCard(pin, position) {
    closeCard();
    const maps = window.kakao.maps;
    state.card = new maps.CustomOverlay({
      position, content: wrapCard(buildCard(pin)), xAnchor: 0.5, yAnchor: 1, zIndex: 20, clickable: true,
    });
    state.card.setMap(state.map);
    setActive(pin.id);
    // 카드가 지도 위쪽에 잘리지 않도록 핀을 지도 아래쪽(가운데에서 140px 아래)에 오게 옮긴다
    const projection = state.map.getProjection();
    const point = projection.containerPointFromCoords(position);
    state.map.panTo(projection.coordsFromContainerPoint(new maps.Point(point.x, point.y - 140)));
  }

  function clearPins() {
    closeCard();
    for (const [marker, listener] of state.listeners) {
      window.kakao.maps.event.removeListener(marker, "click", listener);
    }
    state.listeners = [];
    for (const marker of state.markers) marker.setMap(null);
    for (const overlay of state.overlays) overlay.setMap(null);
    state.markers = [];
    state.overlays = [];
  }

  function syncPins() {
    const pins = state.data.pins || [];
    const serialized = JSON.stringify(pins);
    if (serialized === state.lastPins) return;
    state.lastPins = serialized;
    clearPins();
    state.pinIndex = {};
    const maps = window.kakao.maps;
    const bounds = new maps.LatLngBounds();
    for (const pin of pins) {
      const position = new maps.LatLng(pin.latitude, pin.longitude);
      const marker = new maps.Marker({position, map: state.map, title: pin.label});
      const label = document.createElement("button");
      label.type = "button";
      label.className = "map-pins-label";
      label.textContent = pin.label;
      const overlay = new maps.CustomOverlay({position, content: label, yAnchor: 2.9, map: state.map, clickable: true});
      state.pinIndex[pin.id] = {pin, position};
      const listener = () => openCard(pin, position);
      label.addEventListener("click", event => {
        event.stopPropagation();
        listener();
      });
      maps.event.addListener(marker, "click", listener);
      state.listeners.push([marker, listener]);
      state.markers.push(marker);
      state.overlays.push(overlay);
      bounds.extend(position);
    }
    if (pins.length === 1) {
      state.map.setLevel(3);
      state.map.setCenter(new maps.LatLng(pins[0].latitude, pins[0].longitude));
    } else if (pins.length > 1) {
      state.map.setBounds(bounds, 48);
    }
  }

  function applyGeocode() {
    const request = state.data.geocode;
    if (!request) {
      state.temp?.setMap(null);
      state.temp = null;
      return;
    }
    if (request.id === state.lastGeocode) return;
    state.lastGeocode = request.id;
    const maps = window.kakao.maps;
    setStatus("고른 주소의 위치를 찾고 있습니다.");
    state.geocoder.addressSearch(request.query, (results, status) => {
      if (state.disposed || state.lastGeocode !== request.id) return;
      if (status !== maps.services.Status.OK || !results.length) {
        const notFound = status === maps.services.Status.ZERO_RESULT ||
          (status === maps.services.Status.OK && !results.length);
        setStatus(notFound
          ? "이 주소의 지도 좌표를 찾지 못했습니다. 다른 주소를 골라 주세요."
          : "주소 좌표 변환에 실패했습니다. 카카오 앱 설정과 네트워크를 확인해 주세요.", true);
        state.setState("geocoded", {id: request.id, ok: false, notFound});
        return;
      }
      const result = results[0];
      const picked = request.address || {};
      const latitude = Number(result.y);
      const longitude = Number(result.x);
      const position = new maps.LatLng(latitude, longitude);
      state.temp?.setMap(null);
      state.temp = new maps.Marker({position, map: state.map});
      state.map.setLevel(3);
      state.map.setCenter(position);
      setStatus("고른 주소의 위치입니다. 맞으면 저장하세요.");
      state.setState("geocoded", {
        id: request.id, ok: true, latitude, longitude,
        roadAddress: picked.roadAddress || result.road_address?.address_name || "",
        parcelAddress: picked.parcelAddress || result.address?.address_name || "",
        zonecode: picked.zonecode || result.road_address?.zone_no || "",
        buildingName: picked.buildingName || result.road_address?.building_name || "",
      });
    });
  }

  function buildItem(item) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "map-list-item";
    row.dataset.id = item.id;
    if (item.thumb) {
      const thumb = document.createElement("img");
      thumb.className = "map-list-item__thumb";
      thumb.src = item.thumb;
      thumb.alt = "";
      thumb.loading = "lazy";
      row.append(thumb);
    }
    const body = document.createElement("span");
    body.className = "map-list-item__body";
    const head = document.createElement("span");
    head.className = "map-list-item__head";
    const label = document.createElement("strong");
    label.textContent = item.label;
    const status = document.createElement("span");
    status.className = "map-list-item__status is-" + (item.tone || "none");
    status.textContent = item.status;
    head.append(label, status);
    body.append(head);
    for (const [text, cls] of [[item.meta, "map-list-item__meta"], [item.memo, "map-list-item__memo"],
                               [item.hint, "map-list-item__hint"]]) {
      if (!text) continue;
      const line = document.createElement("span");
      line.className = cls;
      line.textContent = text;
      body.append(line);
    }
    row.append(body);
    row.addEventListener("click", event => {
      event.stopPropagation();
      focusPin(item.id);
    });
    return row;
  }

  function syncPanel() {
    const panel = parentElement.querySelector(".map-pins-panel");
    const info = state.data.panel;
    panel.hidden = !info;
    if (!info) return;
    const serialized = JSON.stringify(info);
    if (serialized === state.lastPanel) return;
    state.lastPanel = serialized;
    panel.replaceChildren();
    if (!panel.__bound) {
      panel.__bound = true;   // 지도 끌기·확대가 목록 스크롤을 가로채지 않게
      for (const type of ["mousedown", "touchstart", "dblclick", "wheel"]) {
        panel.addEventListener(type, event => event.stopPropagation());
      }
    }

    const head = document.createElement("div");
    head.className = "map-pins-panel__head";
    const titles = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = info.title;
    titles.append(title);
    if (info.subtitle) {
      const sub = document.createElement("span");
      sub.textContent = info.subtitle;
      titles.append(sub);
    }
    head.append(titles);
    const items = info.items || [];
    if (items.length) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "map-pins-panel__toggle";
      const list = document.createElement("div");
      list.className = "map-list";
      list.setAttribute("role", "list");
      for (const item of items) list.append(buildItem(item));
      const apply = () => {
        list.hidden = !state.panelOpen;
        toggle.textContent = state.panelOpen ? "접기" : "목록";
        toggle.setAttribute("aria-expanded", String(state.panelOpen));
      };
      toggle.addEventListener("click", event => {
        event.stopPropagation();
        state.panelOpen = !state.panelOpen;
        apply();
      });
      apply();
      head.append(toggle);
      panel.append(head, list);
      setActive(state.activeId);
    } else {
      panel.append(head);
    }
  }

  syncPanel();
  if (state.map) {
    syncPins();
    applyGeocode();
  } else if (!state.started) {
    state.started = true;
    loadSdk(data.apiKey).then(maps => {
      if (state.disposed) return;
      const first = (state.data.pins || [])[0];
      const container = parentElement.querySelector(".map-pins-map");
      if (state.data.fullscreen) {
        container.classList.add("is-fullscreen");
        statusEl.classList.add("is-floating");
      } else {
        container.style.height = (state.data.height || 360) + "px";
      }
      state.map = new maps.Map(container, {
        center: new maps.LatLng(first?.latitude ?? 37.5665, first?.longitude ?? 126.978),
        level: first ? 4 : 7,
      });
      state.geocoder = new maps.services.Geocoder();
      state.mapClick = () => closeCard();
      maps.event.addListener(state.map, "click", state.mapClick);
      state.observer = new ResizeObserver(() => {
        const center = state.map.getCenter();
        state.map.relayout();
        state.map.setCenter(center);
      });
      state.observer.observe(container);
      setStatus("");
      syncPins();
      applyGeocode();
    }).catch(error => setStatus(error.message, true));
  }

  return () => {
    state.disposed = true;
    state.observer?.disconnect();
    if (state.map) {
      clearPins();
      window.kakao.maps.event.removeListener(state.map, "click", state.mapClick);
    }
    state.temp?.setMap(null);
    delete parentElement.__mapPins;
  };
}
"""

PINS_CSS = """
.map-pins-map {
  width: 100%;
  height: 360px;
  border-radius: 12px;
  overflow: hidden;
  background: var(--st-secondary-background-color);
}
.map-pins-label {
  padding: 3px 10px;
  border: 0;
  border-radius: 999px;
  background: #1d4ed8;
  color: #fff;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(29, 78, 216, 0.35);
}
.map-pins-label:hover { background: #1e40af; }
.map-pin-card-wrap { padding-bottom: 84px; pointer-events: none; }
.map-pin-card-wrap .map-pin-card { pointer-events: auto; }
.map-pin-card {
  position: relative;
  box-sizing: border-box;
  width: 232px;
  padding: 14px 16px;
  border-radius: 14px;
  background: #ffffff;
  color: #0f172a;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.45;
  text-align: left;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18), 0 2px 6px rgba(15, 23, 42, 0.08);
}
.map-pin-card::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -7px;
  width: 14px;
  height: 14px;
  background: #ffffff;
  transform: translateX(-50%) rotate(45deg);
  box-shadow: 3px 3px 6px rgba(15, 23, 42, 0.06);
}
.map-pin-card__head { display: flex; align-items: center; justify-content: space-between; }
.map-pin-card__badge {
  padding: 2px 10px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 14px;
  font-weight: 700;
}
.map-pin-card__close {
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #94a3b8;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.map-pin-card__close:hover { background: #f1f5f9; color: #475569; }
.map-pin-card__address { margin: 8px 0 0; color: #64748b; font-size: 12px; word-break: keep-all; }
.map-pin-card__rows {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
}
.map-pin-card__rows dt { margin: 0; color: #64748b; }
.map-pin-card__rows dd { margin: 0; text-align: right; font-weight: 700; color: #0f172a; }
.map-pin-card__rows dd.is-muted { font-weight: 500; color: #94a3b8; }
.map-pin-card__note { margin: 10px 0 0; color: #94a3b8; font-size: 12px; }
.map-pin-card__link {
  display: block;
  margin-top: 12px;
  padding: 9px 0;
  border-radius: 10px;
  background: #1d4ed8;
  color: #ffffff !important;
  font-weight: 600;
  text-align: center;
  text-decoration: none !important;
}
.map-pin-card__link::after { content: " →"; }
.map-pin-card__link:hover { background: #1e40af; }
.map-pins-wrap { position: relative; }
.map-pins-map.is-fullscreen { height: 100vh; border-radius: 0; }
.map-pins-panel {
  position: absolute;
  top: 72px;
  left: 20px;
  z-index: 5;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 340px;
  max-width: calc(100% - 40px);
  max-height: calc(100% - 96px);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.97);
  color: #0f172a;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}
.map-pins-panel[hidden] { display: none; }
.map-pins-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}
.map-pins-panel__head > div { display: flex; flex-direction: column; gap: 2px; }
.map-pins-panel__head strong { font-size: 16px; }
.map-pins-panel__head span { font-size: 12px; color: #64748b; }
.map-pins-panel__toggle {
  flex: none;
  padding: 4px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.map-pins-panel__toggle:hover { background: #f8fafc; }
.map-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 12px 12px;
  overflow-y: auto;
  border-top: 1px solid #f1f5f9;
  padding-top: 12px;
}
.map-list[hidden] { display: none; }
.map-list-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  color: inherit;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.map-list-item:hover { border-color: #93c5fd; }
.map-list-item.is-active { border-color: #1d4ed8; box-shadow: 0 0 0 2px rgba(29, 78, 216, 0.15); }
.map-list-item__thumb {
  flex: none;
  width: 68px;
  height: 52px;
  border-radius: 8px;
  object-fit: cover;
  background: #f1f5f9;
}
.map-list-item__body { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.map-list-item__head { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.map-list-item__head strong { font-size: 14px; }
.map-list-item__status { font-size: 12px; }
.map-list-item__status.is-success { color: #15803d; }
.map-list-item__status.is-none { color: #64748b; }
.map-list-item__status.is-failed { color: #dc2626; }
.map-list-item__status.is-stale { color: #c2410c; font-weight: 600; }
.map-list-item__meta { font-size: 12px; color: #475569; }
.map-list-item__memo {
  display: -webkit-box;
  font-size: 12px;
  color: #64748b;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.map-list-item__hint { font-size: 11px; color: #94a3b8; }
.map-pins-status { margin: 4px 0 0; font-size: 13px; opacity: 0.8; }
.map-pins-status:empty { display: none; }
.map-pins-status.is-floating {
  position: absolute;
  left: 50%;
  bottom: 24px;
  z-index: 5;
  margin: 0;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.78);
  color: #fff;
  opacity: 1;
  transform: translateX(-50%);
}
.map-pins-error { color: #dc2626; opacity: 1; }
"""

def _postcode():
    return st.components.v2.component(
        "map_explorer_postcode",
        html="""
        <p class="map-explorer-postcode-status" role="status">주소 검색창을 불러오는 중입니다.</p>
        <div class="map-explorer-postcode" aria-label="카카오 주소 검색"></div>
        """,
        js=POSTCODE_JS,
        isolate_styles=False,
    )


def _pins():
    return st.components.v2.component(
        "map_listing_pins",
        html="""
        <div class="map-pins-wrap">
          <div class="map-pins-map" role="region" aria-label="매물 위치 지도"></div>
          <div class="map-pins-panel" hidden></div>
          <p class="map-pins-status" role="status">지도를 불러오는 중입니다.</p>
        </div>
        """,
        css=PINS_CSS,
        js=PINS_JS,
        isolate_styles=False,
    )


def current_api_key() -> str:
    """지도 탐색 화면에서 입력한 키 → secrets·환경변수·frontend/.env 순서."""
    typed = str(st.session_state.get(logic.KEY_INPUT) or "").strip()
    return typed or logic.configured_api_key(st.secrets)


def pins_map(api_key: str, pins: list[dict], *, key: str, geocode: dict | None = None,
             height: int = 360, fullscreen: bool = False, panel: dict | None = None):
    """핀 지도. pins = [{id, label, detail, latitude, longitude, rows, note, link}].

    geocode = {id, query, address}를 주면 그 주소를 좌표로 바꿔 임시 핀을 찍고 결과를 돌려준다
    (돌려받은 값의 .geocoded = {id, ok, latitude, longitude, roadAddress, parcelAddress, zonecode, buildingName}).
    핀(또는 이름표)을 누르면 정보 카드가 열린다. 카드의 '매물 상세 보기'를 누르면 .open에 핀 id가 들어 있다.
    핀 항목: rows=[{label, value, muted}], note, link(True면 '매물 상세 보기').
    fullscreen=True면 지도를 화면 높이(100vh)로 그리고, panel={title, subtitle, items}을 왼쪽 위에 띄운다.
    items=[{id, label, status, tone(success·none·failed·stale), meta, memo, hint, thumb}]: 누르면 그 핀으로
    지도가 옮겨 가고 정보 카드가 열린다. 핀을 누르면 목록의 같은 항목이 강조된다.
    """
    return _pins()(
        key=key,
        data={"apiKey": api_key, "pins": pins, "geocode": geocode, "height": height,
              "fullscreen": fullscreen, "panel": panel},
        default={"geocoded": None},
        on_geocoded_change=lambda: None,
        on_open_change=lambda: None,
        height="content" if fullscreen else height + 30,
    )


def pick_address(target_key: str, picker_key: str) -> None:
    """카카오 주소 검색 창을 띄우고, 고른 주소(dict)를 st.session_state[target_key]에 넣고 다시 그린다."""

    @st.dialog("주소 검색")
    def _dialog() -> None:
        result = _postcode()(key=picker_key, on_selected_change=lambda: None, height=510)
        selected = getattr(result, "selected", None)
        if selected:
            st.session_state[target_key] = selected
            st.rerun()

    _dialog()
