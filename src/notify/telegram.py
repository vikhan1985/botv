# -*- coding: utf-8 -*-
# src/notify/telegram.py

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger


class TgNotifier:
    """
    Минимальный Telegram клиент: отправка сообщений и опциональный polling команд.
    """
    def __init__(self, token: Optional[str], chat_id: Optional[str | int]) -> None:
        self.token = (token or "").strip()
        self.chat_id = str(chat_id) if chat_id is not None else ""
        self.base = f"https://api.telegram.org/bot{self.token}"
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _api(self, method: str, params: Dict[str, Any]) -> Any:
        sess = await self._get_session()
        url = f"{self.base}/{method}"
        async with sess.post(url, json=params) as r:
            try:
                data = await r.json()
            except Exception:
                txt = await r.text()
                logger.warning(f"[TG] non-json response {r.status}: {txt}")
                return {"ok": False, "status": r.status, "text": txt}
            return data

    async def send_text(self, text: str) -> Any:
        if not self.token or not self.chat_id:
            return {"ok": False, "reason": "no token/chat_id"}
        return await self._api(
            "sendMessage",
            {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
        )

    # ------------- polling команд (по запросу) -------------
    async def get_updates(self, offset: Optional[int] = None, timeout: int = 0) -> List[Dict[str, Any]]:
        """
        Тянет апдейты getUpdates. Возвращает список апдейтов.
        """
        sess = await self._get_session()
        params = {}
        if offset is not None:
            params["offset"] = offset
        if timeout:
            params["timeout"] = timeout
        url = f"{self.base}/getUpdates"
        async with sess.get(url, params=params) as r:
            data = await r.json(content_type=None)
            if not data.get("ok"):
                return []
            return data.get("result", [])
