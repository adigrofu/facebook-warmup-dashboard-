#!/usr/bin/env python3
"""
Streamlit Dashboard for Meta Page Warmup Configuration
======================================================

What this dashboard does:
1. Fetches all pages owned by your Meta Business Manager.
2. Adds newly discovered pages into pages_config.json automatically.
3. Shows only unconfigured pages in a "New Pages Queue".
4. Lets non-tech users assign Page Type, Theme, Active status, and Posts/Day.
5. Saves everything back to pages_config.json.

Run:
    streamlit run dashboard.py

Required .secrets.env:
    META_SYSTEM_USER_TOKEN=your_token_here
    META_BUSINESS_ID=587291318723707
"""

import io
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

import requests
import streamlit as st

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "pages_config.json")
BLACKLIST_PATH = os.path.join(SCRIPT_DIR, "blacklist.json")
ENV_PATH = os.path.join(SCRIPT_DIR, ".secrets.env")
GRAPH_VERSION = "v23.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

PAGE_TYPES = {
    "animals_pets": "Animals & Pets",
    "spiritual": "Spiritual",
}

THEMES_BY_PAGE_TYPE = {
    "animals_pets": {
        "cats": "Cats",
        "dogs": "Dogs",
    },
    "spiritual": {
        "spiritual": "Spiritual",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with io.open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with io.open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: Dict[str, Any]) -> None:
    with io.open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_blacklist() -> Dict[str, Any]:
    if not os.path.exists(BLACKLIST_PATH):
        return {"blacklisted_pages": {}}
    with io.open(BLACKLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_blacklist(blacklist: Dict[str, Any]) -> None:
    with io.open(BLACKLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(blacklist, f, indent=2, ensure_ascii=False)


def is_blacklisted(page_id: str, blacklist: Dict[str, Any]) -> bool:
    return str(page_id) in blacklist.get("blacklisted_pages", {})


def filter_out_blacklisted(pages: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    """Hide blacklisted pages from a view WITHOUT deleting their config.

    Blacklisting must never destroy a page's saved settings, so that Restore
    can bring the page back exactly as it was. Enforcement is read-time only:
    blacklisted pages are excluded from the queues here and skipped by the
    posting worker, but their entry stays in pages_config.json untouched.
    """
    return {
        pid: data
        for pid, data in pages.items()
        if not is_blacklisted(pid, blacklist)
    }


def fetch_owned_pages(token: str, business_id: str) -> List[Dict[str, str]]:
    pages: List[Dict[str, str]] = []
    url = f"{GRAPH_BASE_URL}/{business_id}/owned_pages"
    params = {
        "access_token": token,
        "fields": "id,name",
        "limit": 500,
    }

    while url:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        pages.extend(payload.get("data", []))
        url = payload.get("paging", {}).get("next")
        params = None  # paging.next already contains query params

    return pages


def sync_pages_to_config(meta_pages: List[Dict[str, str]], config: Dict[str, Any]) -> int:
    added_count = 0
    for page in meta_pages:
        page_id = str(page.get("id"))
        page_name = page.get("name", "")
        if not page_id:
            continue

        if page_id not in config:
            config[page_id] = {
                "page_id": page_id,
                "page_name": page_name,
                "page_type": None,
                "theme": None,
                "enabled": False,
                "posts_per_day": 1,
                "discovered_at": now_iso(),
                "configured_at": None,
                "last_posted_at": None,
            }
            added_count += 1
        else:
            # Keep name updated if it changes in Meta, but do not overwrite user settings.
            config[page_id]["page_name"] = page_name
            config[page_id]["page_id"] = page_id

    return added_count


def get_new_pages(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        page_id: data
        for page_id, data in config.items()
        if not data.get("configured_at")
    }


def get_configured_pages(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        page_id: data
        for page_id, data in config.items()
        if data.get("configured_at")
    }


def theme_options_for(page_type: str) -> Dict[str, str]:
    if not page_type:
        return {}
    return THEMES_BY_PAGE_TYPE.get(page_type, {})


def render_page_editor(page_id: str, data: Dict[str, Any], key_prefix: str) -> Dict[str, Any]:
    st.markdown(f"**{data.get('page_name', 'Unknown Page')}**")
    st.caption(f"Page ID: {page_id}")

    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])

    current_page_type = data.get("page_type") or "animals_pets"
    page_type = c1.selectbox(
        "Page Type",
        options=list(PAGE_TYPES.keys()),
        format_func=lambda x: PAGE_TYPES[x],
        index=list(PAGE_TYPES.keys()).index(current_page_type) if current_page_type in PAGE_TYPES else 0,
        key=f"{key_prefix}_page_type_{page_id}",
    )

    theme_options = theme_options_for(page_type)
    current_theme = data.get("theme")
    theme_keys = list(theme_options.keys())
    if current_theme not in theme_keys:
        current_theme = theme_keys[0] if theme_keys else None

    theme = c2.selectbox(
        "Theme",
        options=theme_keys,
        format_func=lambda x: theme_options[x],
        index=theme_keys.index(current_theme) if current_theme in theme_keys else 0,
        key=f"{key_prefix}_theme_{page_id}",
    ) if theme_keys else None

    enabled = c3.checkbox(
        "Active",
        value=bool(data.get("enabled", False)),
        key=f"{key_prefix}_enabled_{page_id}",
    )

    posts_per_day = c4.number_input(
        "Posts/Day",
        min_value=0,
        max_value=20,
        value=int(data.get("posts_per_day", 1)),
        step=1,
        key=f"{key_prefix}_ppd_{page_id}",
    )

    return {
        **data,
        "page_id": page_id,
        "page_name": data.get("page_name", ""),
        "page_type": page_type,
        "theme": theme,
        "enabled": bool(enabled),
        "posts_per_day": int(posts_per_day),
    }


def main() -> None:
    load_env_file(ENV_PATH)
    token = os.getenv("META_SYSTEM_USER_TOKEN", "")
    business_id = os.getenv("META_BUSINESS_ID", "")

    st.set_page_config(page_title="Page Warmup Manager", layout="wide")
    st.title("Page Warmup Manager")
    st.caption("Manage Meta pages without editing code or JSON manually.")

    if not token:
        st.error("META_SYSTEM_USER_TOKEN is missing in .secrets.env")
        st.stop()
    if not business_id:
        st.error("META_BUSINESS_ID is missing in .secrets.env")
        st.stop()

    config = load_config()
    blacklist = load_blacklist()

    # Counts reflect only pages that are actually actionable (blacklisted pages
    # are hidden from the queues and skipped by the worker, so they don't count).
    visible = filter_out_blacklisted(config, blacklist)

    top1, top2, top3, top4 = st.columns(4)
    top1.metric("Total Pages", len(visible))
    top2.metric("New Pages", len(get_new_pages(visible)))
    top3.metric("Active Pages", sum(1 for p in visible.values() if p.get("enabled")))
    top4.metric("Configured Pages", len(get_configured_pages(visible)))

    if st.button("Sync Pages From Meta", type="primary"):
        try:
            meta_pages = fetch_owned_pages(token, business_id)

            meta_pages = [
                page for page in meta_pages
                if not is_blacklisted(str(page.get("id")), blacklist)
            ]

            added = sync_pages_to_config(meta_pages, config)
            save_config(config)
            st.success(f"Synced {len(meta_pages)} pages. Added {added} new pages.")
            st.rerun()
        except Exception as e:
            st.error(f"Sync failed: {e}")

    tab_new, tab_all, tab_blacklist, tab_controls = st.tabs(
        ["New Pages Queue", "All Pages", "Blacklisted Pages", "Global Controls"]
    )

    with tab_new:
        st.subheader("New Pages Requiring Setup")
        new_pages = filter_out_blacklisted(get_new_pages(config), blacklist)

        if not new_pages:
            st.success("No new pages need setup.")
        else:
            st.info("Assign page type, theme, active status, and posts/day. Then click Save New Pages.")
            updates: Dict[str, Any] = {}
            for page_id, data in sorted(new_pages.items(), key=lambda item: item[1].get("page_name", "")):
                with st.container(border=True):
                    updates[page_id] = render_page_editor(page_id, data, "new")

            if st.button("Save New Pages", type="primary"):
                for page_id, updated in updates.items():
                    updated["configured_at"] = now_iso()
                    config[page_id] = updated
                save_config(config)
                st.success("New pages saved.")
                st.rerun()

    with tab_all:
        st.subheader("All Configured Pages")
        configured_pages = filter_out_blacklisted(get_configured_pages(config), blacklist)
        search = st.text_input("Search pages", "")
        page_type_filter = st.selectbox(
            "Filter by Page Type",
            options=["all"] + list(PAGE_TYPES.keys()),
            format_func=lambda x: "All" if x == "all" else PAGE_TYPES[x],
        )

        filtered = configured_pages
        if search.strip():
            s = search.lower().strip()
            filtered = {pid: d for pid, d in filtered.items() if s in d.get("page_name", "").lower() or s in pid}
        if page_type_filter != "all":
            filtered = {pid: d for pid, d in filtered.items() if d.get("page_type") == page_type_filter}

        if not filtered:
            st.warning("No configured pages found for this filter.")
        else:
            updates = {}
            for page_id, data in sorted(filtered.items(), key=lambda item: item[1].get("page_name", "")):
                with st.container(border=True):
                    updates[page_id] = render_page_editor(page_id, data, "all")

            if st.button("Save All Page Changes"):
                for page_id, updated in updates.items():
                    if not updated.get("configured_at"):
                        updated["configured_at"] = now_iso()
                    config[page_id] = updated
                save_config(config)
                st.success("Changes saved.")
                st.rerun()

    with tab_blacklist:
        st.subheader("Blacklisted Pages")
        blacklist = load_blacklist()
        blacklisted_pages = blacklist.get("blacklisted_pages", {})

        st.metric("Blacklisted Pages", len(blacklisted_pages))

        if not blacklisted_pages:
            st.success("No pages are blacklisted.")
        else:
            for page_id, data in sorted(
                blacklisted_pages.items(),
                key=lambda item: item[1].get("page_name", "")
            ):
                c1, c2 = st.columns([4, 1])
                c1.write(f"**{data.get('page_name', 'Unknown Page')}**")
                c1.caption(f"Page ID: {page_id}")

                if c2.button("Restore", key=f"restore_{page_id}"):
                    blacklisted_pages.pop(page_id, None)
                    blacklist["blacklisted_pages"] = blacklisted_pages
                    save_blacklist(blacklist)
                    st.success("Page restored. It can appear again on next sync.")
                    st.rerun()

    with tab_controls:
        st.subheader("Safety Controls")
        c1, c2 = st.columns(2)
        if c1.button("Pause All Posting"):
            for page in config.values():
                page["enabled"] = False
            save_config(config)
            st.warning("All pages disabled.")
            st.rerun()

        if c2.button("Enable Only Animals & Pets"):
            for page in config.values():
                page["enabled"] = page.get("page_type") == "animals_pets" and bool(page.get("theme"))
            save_config(config)
            st.success("Only configured Animals & Pets pages are enabled.")
            st.rerun()

        st.download_button(
            "Download pages_config.json",
            data=json.dumps(config, indent=2, ensure_ascii=False),
            file_name="pages_config.json",
            mime="application/json",
        )


if __name__ == "__main__":
    main()
