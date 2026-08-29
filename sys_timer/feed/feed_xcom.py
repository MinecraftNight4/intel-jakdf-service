import json
import os
from typing import Dict, Any
from logger import info, warn, crit, log

import discord
import asyncio
from discord.ext import commands


# -------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------- 
XCOM_FILE  = "sys_save/request_xcom.json"
SETUP_FILE = "sys_save/feed_system_setup.json"
DATA_FILE  = "sys_save/feed_system_data.json"


def load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default.copy() if isinstance(default, dict) else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy() if isinstance(default, dict) else default


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def process_feed_xcom(bot: commands.Bot) -> int:
    storage_data = load_json(DATA_FILE, {})
    storage_feed = load_json(SETUP_FILE, {})
    storage_news: Dict[str, Any] = load_json(XCOM_FILE, {})
    storage_sent = 0


    #==================#
    # ACCOUNT INDEXING #
    #==================#
    process_user_list = list(storage_news.keys())
    log(f"[FEED - XCOM]: Creating {len(process_user_list)}] instances...", "feed", show=False)
    for account_read in process_user_list:
        # [!] MEMO FOR FUTURE ME:
        # account_info = DATA FROM DB under the section of the feed
        # account_tool = Verification of content based on HASH
        # account_data = Stored Data based on Hash verification
        account_info_name = f"xcom-{account_read.lower()}"
        account_info_post_hash = set(storage_data.get(account_info_name, []))
        account_info_post_save = (storage_news.get(account_read) or {}).get("status") or {}
        account_info_post_feed = storage_feed.get(account_info_name) or {}
        
        
        account_tool_hash = set()
        account_tool_data = {}
        for post_data in account_info_post_save.values():
            post_hash = post_data.get("hash")
            if post_hash:
                account_tool_hash.add(post_hash)
                account_tool_data[post_hash] = post_data
        account_data_hash = account_tool_hash - account_info_post_hash
        account_data_list = [account_tool_data[hash] for hash in account_data_hash]


        debug_all_feed = len(account_info_post_feed)
        debug_all_post = len(account_info_post_save)
        debug_can_post = len(account_data_list)
        log(f"[FEED - XCOM]: [TARGET: @{account_read.upper()}] [CHANNELS: {debug_all_feed}] [ARTICLES: {debug_can_post}/{debug_all_post}]", "feed", show=False)


        #=========================#
        # CLOSE THREAD BY ACCOUNT #
        #=========================#
        if (not account_data_hash) or (0 >= debug_all_feed):
            storage_data[account_info_name] = list(account_tool_hash)
            log(f"[FEED - XCOM]: [TARGET: @{account_read.upper()}] SECTION SKIPPED...", "feed", show=False)
            log(f" ", "feed", show=False)
            continue


        #==============================#
        # MESSAGE DELIVERY PER ACCOUNT #
        #==============================#
        log(f"[FEED - XCOM]: [TARGET: @{account_read.upper()}] SENDING ARTICLES... ", "feed", show=False)
        debug_post_sent = 0
        for guild_data in account_info_post_feed.values():


            feed_data_hold = bot.get_channel(int(guild_data.get("channel")))
            if feed_data_hold is None:
                try:
                    feed_data_hold = await bot.fetch_channel(int(guild_data.get("channel")))
                except Exception:
                    log(f"- [(!) FAILURE] #ERROR_FLAG_0001 | #{guild_data.get("channel")}", "feed", level="CRIT", show=False)
                continue
            
            feed_data_post = getattr(feed_data_hold, "is_news", lambda: False)()
            feed_data_rule = bool(guild_data.get("publish", False))
            log(f"- [ID: {guild_data.get("channel")}] | [IS_NEWS: {feed_data_post}] | [PUBLISH: {feed_data_rule}]", "feed", show=False)



            for post in account_data_list:
                post_uuid = post.get("uuid") or ""
                post_link = post.get("link") or ""
                post_hash = post.get("hash") or ""
                post_item = f"[`🔗`](https://fxtwitter.com/i/status/{post_uuid}) <{post_link}>\n-# *Embed powered by: [`🔗`](<https://docs.fxembed.com/>) FxEmbed*"


                await asyncio.sleep(2)
                try:
                    message_sent = await asyncio.wait_for(feed_data_hold.send(content=post_item), timeout=10.0)
                    log(f"  - [SEND: SUCCESS] | #{post_hash} - {post_link}", "feed", show=False)


                    if feed_data_post and feed_data_rule:
                        try:
                            await asyncio.wait_for(message_sent.publish(), timeout=5.0)
                            log(f"      ⤷ CROSSPOST: SUCCESS", "feed", show=False)
                        except Exception as e:
                            log(f"      ⤷ [(!) FAILURE] #ERROR_FLAG_0002 | {e}", "feed", level="WARN", show=False)  
                except Exception as e:
                    log(f"  - [(!) FAILURE] #ERROR_FLAG_0003 | #{post_hash} - {post_link} | DUMP: {e}", "feed", level="CRIT", show=False)
                    continue
                debug_post_sent += 1


            feed_ping_text = guild_data.get("text")
            if feed_ping_text and str(feed_ping_text).strip():
                await asyncio.sleep(2)
                try:
                    await asyncio.wait_for(feed_data_hold.send(content=str(feed_ping_text).strip()), timeout=5.0)
                    log(f"    ⤷ PING: SUCCESS", "feed", show=False)
                except Exception as e:
                    log(f"    ⤷ [(!) FAILURE] #ERROR_FLAG_0003 | DUMP: {e} ", "feed", level="CRIT", show=False)
                    continue
            storage_sent += debug_post_sent


        storage_data[account_info_name] = list(account_tool_hash)
        log(f"[FEED - XCOM]: [TARGET: @{account_read.upper()}] [SENT x{debug_post_sent}]", "feed", show=False)
        log(f"[FEED - XCOM]: ", "feed", show=False)
        
    save_json(DATA_FILE, storage_data)
    log(f"[FEED - XCOM]: [SENT: {storage_sent}]", "feed", show=False)
    log(f"[FEED - XCOM]: THREAD CLOSED.", "feed", show=False)
    log(f"[FEED - XCOM]: ", "feed", show=False)
    return storage_sent
