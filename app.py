"""쇼핑 리스트 Streamlit 앱."""

import json
import shutil
import string
import threading
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

DATA_FILE = Path(__file__).parent / "shopping_list.json"
CORRUPT_FILE = DATA_FILE.with_suffix(".corrupt.json")
MAX_NAME_LEN = 50
MIN_QTY, MAX_QTY = 1, 999
WORD_JOINER = "⁠"  # 자동 링크를 끊는 보이지 않는 문자


# ---------- 데이터 ----------

@st.cache_resource
def get_lock() -> threading.Lock:
    """모든 세션(탭)이 함께 쓰는 파일 잠금을 돌려준다."""
    return threading.Lock()


def normalize_item(raw) -> dict | None:
    """저장 파일의 아이템 하나를 올바른 형태로 고친다. 쓸 수 없으면 None."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        quantity = int(raw.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    item_id = raw.get("id")
    created_at = raw.get("created_at")
    return {
        "id": item_id if isinstance(item_id, str) and item_id else uuid.uuid4().hex,
        "name": name.strip()[:MAX_NAME_LEN],
        "quantity": min(max(quantity, MIN_QTY), MAX_QTY),
        "checked": raw.get("checked") is True,
        "created_at": created_at if isinstance(created_at, str)
        else datetime.now().isoformat(timespec="seconds"),
    }


def read_items() -> tuple[list[dict], str | None]:
    """파일에서 아이템을 읽어 (목록, 경고 메시지)를 돌려준다. 잠금 안에서 호출한다."""
    if not DATA_FILE.exists():
        return [], None
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        data = None
    if not isinstance(data, list):
        shutil.copyfile(DATA_FILE, CORRUPT_FILE)
        save_items([])
        return [], (
            "저장 파일이 손상되어 빈 목록으로 시작합니다. "
            f"원본은 {CORRUPT_FILE.name}에 백업했습니다."
        )
    items, seen = [], set()
    for raw in data:
        item = normalize_item(raw)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    if items != data:
        save_items(items)  # 고친 내용을 저장해 두어야 새로 만든 id가 매번 바뀌지 않는다
        return items, "저장 파일의 일부 아이템 형식이 올바르지 않아 고치거나 제외했습니다."
    return items, None


def load_items() -> list[dict]:
    """파일에서 최신 목록을 읽고, 문제가 있으면 경고를 표시한다."""
    with get_lock():
        items, warning = read_items()
    if warning:
        st.warning(warning)
    return items


def save_items(items: list[dict]) -> None:
    """아이템 목록을 JSON 파일에 저장한다."""
    DATA_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def modify_items(change) -> None:
    """파일의 최신 목록에 change(items)를 적용하고 저장한다. 다른 탭의 변경을 덮어쓰지 않는다."""
    with get_lock():
        items, _ = read_items()
        change(items)
        save_items(items)
    st.session_state["items"] = items


# ---------- 상태 ----------

def init_state() -> None:
    """session_state를 초기화하고 목록을 파일에서 새로 읽는다."""
    st.session_state["items"] = load_items()
    if "editing_id" not in st.session_state:
        st.session_state["editing_id"] = None
    st.session_state.setdefault("add_error", None)
    st.session_state.setdefault("edit_error", None)


def find_item(item_id: str) -> dict | None:
    """id로 아이템을 찾는다."""
    return next((i for i in st.session_state["items"] if i["id"] == item_id), None)


def validate(name: str, quantity) -> tuple[str | None, int | None, str | None]:
    """이름과 수량을 검증해 (정리된 이름, 수량, 오류 메시지)를 돌려준다."""
    name = (name or "").strip()
    if not name:
        return None, None, "아이템 이름을 입력해 주세요."
    if len(name) > MAX_NAME_LEN:
        return None, None, f"이름은 {MAX_NAME_LEN}자 이하로 입력해 주세요. (현재 {len(name)}자)"
    try:
        qty = int(str(quantity).strip())
    except (TypeError, ValueError):
        qty = None
    if qty is None or not (MIN_QTY <= qty <= MAX_QTY):
        return None, None, f"수량은 {MIN_QTY}~{MAX_QTY} 사이의 정수로 입력해 주세요."
    return name, qty, None


def escape_md(text: str) -> str:
    """마크다운·Streamlit 문법으로 해석되지 않게 문장부호를 HTML 엔티티로 바꾼다."""
    out = []
    for c in text:
        if c in ".:/@":  # URL·도메인 자동 링크도 끊는다
            out.append(f"{WORD_JOINER}&#{ord(c)};{WORD_JOINER}")
        elif c in string.punctuation:
            out.append(f"&#{ord(c)};")
        else:
            out.append(c)
    return "".join(out)


# ---------- 기능 ----------

def add_item(name: str, quantity: int) -> None:
    """새 아이템을 추가한다."""
    new = {
        "id": uuid.uuid4().hex,
        "name": name,
        "quantity": int(quantity),
        "checked": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    modify_items(lambda items: items.append(new))


def update_item(item_id: str, name: str, quantity: int) -> None:
    """아이템의 이름과 수량을 수정한다."""
    def change(items):
        for i in items:
            if i["id"] == item_id:
                i["name"], i["quantity"] = name, int(quantity)
    modify_items(change)


def delete_item(item_id: str) -> None:
    """아이템을 삭제한다."""
    def change(items):
        items[:] = [i for i in items if i["id"] != item_id]
    modify_items(change)
    if st.session_state["editing_id"] == item_id:
        st.session_state["editing_id"] = None


def toggle_item(item_id: str) -> None:
    """아이템의 체크 상태를 체크박스 값에 맞춘다."""
    checked = st.session_state[f"check_{item_id}"]

    def change(items):
        for i in items:
            if i["id"] == item_id:
                i["checked"] = checked
    modify_items(change)


def clear_checked() -> int:
    """체크된 아이템을 모두 삭제하고 삭제한 개수를 돌려준다."""
    removed = []

    def change(items):
        removed.extend(i["id"] for i in items if i["checked"])
        items[:] = [i for i in items if not i["checked"]]
    modify_items(change)
    if st.session_state["editing_id"] in removed:
        st.session_state["editing_id"] = None
    return len(removed)


# ---------- 콜백 ----------

def on_add() -> None:
    """추가 폼 제출을 처리한다."""
    name, qty, error = validate(
        st.session_state.get("add_name"), st.session_state.get("add_qty")
    )
    st.session_state["add_error"] = error
    if name:
        add_item(name, qty)
        st.toast(f"{escape_md(name)} 추가됨", icon="🛒")


def on_delete(item_id: str) -> None:
    """아이템을 삭제하고 알림을 띄운다."""
    item = find_item(item_id)
    delete_item(item_id)
    if item:
        st.toast(f"{escape_md(item['name'])} 삭제됨", icon="🗑️")


def on_clear_checked() -> None:
    """체크된 아이템을 지우고 알림을 띄운다."""
    count = clear_checked()
    st.toast(f"완료 항목 {count}개 삭제됨", icon="🧹")


def on_start_edit(item_id: str) -> None:
    """아이템을 수정 모드로 전환한다."""
    item = find_item(item_id)
    if not item:
        return
    st.session_state["editing_id"] = item_id
    st.session_state["edit_error"] = None
    st.session_state[f"edit_name_{item_id}"] = item["name"]
    st.session_state[f"edit_qty_{item_id}"] = str(item["quantity"])


def on_save_edit(item_id: str) -> None:
    """수정 내용을 검증하고 저장한다."""
    name, qty, error = validate(
        st.session_state.get(f"edit_name_{item_id}"),
        st.session_state.get(f"edit_qty_{item_id}"),
    )
    st.session_state["edit_error"] = error
    if name:
        update_item(item_id, name, qty)
        st.session_state["editing_id"] = None


def on_cancel_edit() -> None:
    """수정 모드를 취소한다."""
    st.session_state["editing_id"] = None
    st.session_state["edit_error"] = None


# ---------- 화면 ----------

CSS = """
<style>
/* 추가 폼과 아이템 행은 모바일에서도 한 줄 유지 */
.st-key-add_row [data-testid="stHorizontalBlock"],
[class*="st-key-row_"] [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 0.5rem;
}
.st-key-add_row [data-testid="stColumn"],
[class*="st-key-row_"] [data-testid="stColumn"] {
    min-width: 0 !important;
}
/* 버튼 칸은 내용 폭만큼만 차지하고 글자가 줄바꿈되지 않게 */
.st-key-add_row [data-testid="stColumn"]:has(button),
[class*="st-key-row_"] [data-testid="stColumn"]:has(button) {
    flex: 0 0 auto !important;
    width: auto !important;
}
.st-key-add_row button,
[class*="st-key-row_"] button {
    min-width: 2.75rem;
    white-space: nowrap;
}
/* 체크박스 라벨이 길면 줄바꿈 */
[class*="st-key-row_"] [data-testid="stCheckbox"] label p {
    word-break: break-all;
}
</style>
"""


def item_label(item: dict) -> str:
    """체크박스 라벨(마크다운)을 만든다."""
    name = escape_md(item["name"])
    qty = f"x{item['quantity']}"
    if item["checked"]:
        return f":gray[~~{name} {qty}~~]"
    return f"**{name}** :gray[:small[{qty}]]"


def render_add_form() -> None:
    """아이템 추가 폼을 그린다."""
    with st.form("add_form", clear_on_submit=True, border=False):
        with st.container(key="add_row"):
            col_name, col_qty, col_btn = st.columns(
                [5, 1.5, 1.4], vertical_alignment="bottom"
            )
            col_name.text_input(
                "아이템 이름", key="add_name",
                placeholder=f"예: 우유 (최대 {MAX_NAME_LEN}자)",
            )
            # number_input은 범위 밖 값·Enter 제출 시 이전 값을 보내므로 텍스트로 받아 검증한다
            col_qty.text_input(
                "수량", key="add_qty", value="1",
                placeholder=f"{MIN_QTY}~{MAX_QTY}",
            )
            col_btn.form_submit_button(
                "추가", type="primary", on_click=on_add, width="stretch"
            )
    if st.session_state["add_error"]:
        st.warning(st.session_state["add_error"])
        st.session_state["add_error"] = None


def render_progress(items: list[dict]) -> None:
    """진행 현황을 그린다."""
    if not items:
        return
    done = sum(1 for i in items if i["checked"])
    st.progress(done / len(items), text=f"전체 {len(items)}개 중 {done}개 완료")


def render_edit_row(item: dict) -> None:
    """수정 모드인 아이템 한 줄을 그린다."""
    item_id = item["id"]
    with st.container(border=True, key=f"row_{item_id}"):
        col_name, col_qty, col_save, col_cancel = st.columns(
            [4, 1.5, 1.3, 1.3], vertical_alignment="center"
        )
        col_name.text_input(
            "이름", key=f"edit_name_{item_id}", label_visibility="collapsed",
        )
        col_qty.text_input(
            "수량", key=f"edit_qty_{item_id}", label_visibility="collapsed",
        )
        col_save.button("저장", key=f"save_{item_id}", type="primary",
                        on_click=on_save_edit, args=(item_id,), width="stretch")
        col_cancel.button("취소", key=f"cancel_{item_id}",
                          on_click=on_cancel_edit, width="stretch")
        if st.session_state["edit_error"]:
            st.warning(st.session_state["edit_error"])


def render_item(item: dict) -> None:
    """아이템 한 줄을 그린다."""
    item_id = item["id"]
    if st.session_state["editing_id"] == item_id:
        render_edit_row(item)
        return

    # 다른 탭에서 바뀐 체크 상태도 보이도록 파일 값으로 맞춘다
    st.session_state[f"check_{item_id}"] = item["checked"]
    with st.container(key=f"row_{item_id}"):
        col_check, col_edit, col_del = st.columns(
            [6, 1, 1], vertical_alignment="center"
        )
        col_check.checkbox(
            item_label(item), key=f"check_{item_id}",
            on_change=toggle_item, args=(item_id,),
        )
        col_edit.button("✏️", key=f"edit_{item_id}", help="수정",
                        on_click=on_start_edit, args=(item_id,), width="stretch")
        col_del.button("🗑️", key=f"del_{item_id}", help="삭제",
                       on_click=on_delete, args=(item_id,), width="stretch")


def main() -> None:
    """앱 화면을 그린다."""
    st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()

    st.title("🛒 쇼핑 리스트")
    render_add_form()
    st.divider()

    items = st.session_state["items"]
    if not items:
        st.info("아직 아이템이 없습니다. 위에서 추가해 보세요.", icon="📝")
        return

    render_progress(items)
    # 미완료 먼저, 각 그룹 안에서는 추가된 순서
    for item in sorted(items, key=lambda i: (i["checked"], i["created_at"])):
        render_item(item)

    st.divider()
    has_checked = any(i["checked"] for i in items)
    _, col_clear, _ = st.columns([1, 2, 1])
    col_clear.button("체크된 항목 지우기", on_click=on_clear_checked,
                     disabled=not has_checked, width="stretch")


main()
