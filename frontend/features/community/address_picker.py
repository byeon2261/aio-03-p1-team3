"""카카오 우편번호(주소 검색) 창으로 지번 주소를 고른다. 키가 필요 없는 서비스다.

변건형님 지도 데모(demo_st/main.py)의 주소 검색 방식을 그대로 따라 주소 모양을 맞춘다.
검색창을 불러오지 못하면 입력칸에 직접 적어도 된다(서버가 공백·"번지"를 정리한다).
import 시 st 함수를 부르지 않는다(컴포넌트는 처음 쓸 때 만든다).
"""

from __future__ import annotations

import streamlit as st

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
  let state = parentElement.__balpumPostcode;
  if (!state) {
    state = {disposed: false};
    parentElement.__balpumPostcode = state;
    const status = parentElement.querySelector(".balpum-postcode-status");
    const container = parentElement.querySelector(".balpum-postcode");
    loadPostcode().then(Postcode => {
      if (state.disposed) return;
      status.textContent = "도로명, 지번 또는 건물명으로 검색한 뒤 주소를 고르세요. 지번 주소로 저장됩니다.";
      state.picker = new Postcode({
        width: "100%", height: 450,
        oncomplete: selected => {
          if (state.disposed) return;
          state.emit("selected", {
            parcelAddress: selected.jibunAddress || selected.autoJibunAddress || "",
            roadAddress: selected.roadAddress || "",
            address: selected.address || "",
          });
        },
      });
      state.picker.embed(container);
    }).catch(error => {
      if (!state.disposed) status.textContent = error.message + " 창을 닫고 주소를 직접 입력해 주세요.";
    });
  }
  state.emit = setTriggerValue;
  return () => {
    state.disposed = true;
    parentElement.querySelector(".balpum-postcode").replaceChildren();
    delete parentElement.__balpumPostcode;
  };
}
"""

_component = None


def _postcode():
    global _component
    if _component is None:
        _component = st.components.v2.component(
            "balpum_postcode",
            html="""
            <p class="balpum-postcode-status" role="status">주소 검색창을 불러오는 중입니다.</p>
            <div class="balpum-postcode" aria-label="카카오 주소 검색"></div>
            """,
            js=POSTCODE_JS,
            isolate_styles=False,
        )
    return _component


def pick_address(selected: dict | None) -> str:
    """검색창이 돌려준 값 → 저장할 지번 주소. 지번이 없으면 기본 주소."""
    selected = selected or {}
    return (selected.get("parcelAddress") or selected.get("address") or selected.get("roadAddress") or "").strip()


def open_search_dialog(target_key: str) -> None:
    """주소 검색 창을 띄우고, 고르면 st.session_state[target_key]에 지번 주소를 넣고 다시 그린다."""

    @st.dialog("주소 검색")
    def _dialog() -> None:
        result = _postcode()(key=f"{target_key}_picker", on_selected_change=lambda: None, height=510)
        address = pick_address(getattr(result, "selected", None))
        if address:
            st.session_state[target_key] = address
            st.rerun()

    _dialog()
