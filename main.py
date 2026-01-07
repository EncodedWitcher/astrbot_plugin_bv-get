import re
import aiohttp
from urllib.parse import urlparse
import html

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Json, Plain, Image

@register("bv-get", "BYSSTED", "bv号获取插件", "1.3.0")
class BvPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        self.timeout = 10
        self.bv_pattern = re.compile(r'BV1[A-Za-z0-9]{9}')

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def bv_get(self, event: AstrMessageEvent):
        """获取 Bilibili 链接并解析"""
        message_obj = event.message_obj
        
        async with aiohttp.ClientSession() as session:
            bv_id = await self.get_from_msg(message_obj, session)
            
            if bv_id:
                logger.info(f"Found BV ID: {bv_id}")
                result = await self.get_bilibili_video_info(bv_id, session)
                if result:
                    title, pic = result
                    chain = [
                        Plain(f'{bv_id}\n标题: {title}\n'),
                    ]
                    
                    # 尝试下载图片并以 bytes 发送，避免 rich media transfer failed
                    try:
                        async with session.get(pic, headers=self.headers, timeout=self.timeout) as img_resp:
                            if img_resp.status == 200:
                                img_data = await img_resp.read()
                                chain.append(Image.fromBytes(img_data))
                            else:
                                chain.append(Image.fromURL(pic)) # 降级尝试
                    except Exception as e:
                        logger.warning(f"Failed to download image: {e}")
                        chain.append(Image.fromURL(pic)) # 降级尝试

                    yield event.chain_result(chain)

    async def get_from_msg(self, message_obj, session: aiohttp.ClientSession):
        """从消息对象中提取 BV 号"""
        # 1. 尝试从 JSON 组件（小程序/卡片）中提取
        for component in message_obj.message:
            if isinstance(component, Json):
                bv = await self._extract_from_json(component, session)
                if bv:
                    return bv
        
        # 2. 尝试从纯文本中提取
        for component in message_obj.message:
            if isinstance(component, Plain):
                bv = await self._extract_from_text(component.text, session)
                if bv:
                    return bv
                    
        return None

    async def _extract_from_json(self, component: Json, session: aiohttp.ClientSession):
        """从 JSON 组件通过 raw_link 提取"""
        try:
            data = component.data
            meta = data.get('meta')
            if not meta:
                return None

            raw_url = ""
            if 'detail_1' in meta:
                raw_url = meta['detail_1'].get('qqdocurl')
            elif 'news' in meta:
                raw_url = meta['news'].get('jumpUrl')
            
            if raw_url:
                cleaned_url = raw_url.split('?')[0]
                return await self.extract_bv(raw_url, session)
                
        except Exception as e:
            logger.error(f"Error extracting from JSON: {e}")
        return None

    async def _extract_from_text(self, text: str, session: aiohttp.ClientSession):
        """从文本中提取 BV 号或解析 URL"""
        match = self.bv_pattern.search(text)
        if match:
            return match.group()
            
        urls = re.findall(r'https?://[^\s]+', text)
        for url in urls:
            bv = await self.extract_bv(url, session)
            if bv:
                return bv
        return None

    async def extract_bv(self, url: str, session: aiohttp.ClientSession):
        """从 URL 提取 BV 号 (包含短链解析)"""
        if not url:
            return None
        
        final_url = await self._resolve_short_url(url, session)
        return self._extract_bv_from_url(final_url)

    async def _resolve_short_url(self, url: str, session: aiohttp.ClientSession):
        """解析 b23.tv 等短链接"""
        parsed = urlparse(url)
        if self._is_b23_link(parsed.netloc):
            try:
                async with session.get(url, headers=self.headers, timeout=self.timeout, allow_redirects=True) as response:
                    return str(response.url)
            except Exception as e:
                logger.warning(f"Short link resolve error: {e}")
                return url
        return url

    def _is_b23_link(self, netloc: str):
        return netloc in {'b23.tv', 'www.b23.tv'} or netloc.endswith('.b23.tv')

    def _extract_bv_from_url(self, url: str):
        match = self.bv_pattern.search(url)
        return match.group() if match else None

    async def get_bilibili_video_info(self, bv_id: str, session: aiohttp.ClientSession):
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
        
        try:
            async with session.get(url, headers=self.headers, timeout=self.timeout) as response:
                if response.status != 200:
                    logger.warning(f"Bilibili API returned status: {response.status}")
                    return None
                
                data = await response.json()
            
            if data.get("code") == 0:
                video_info = data.get("data", {})
                title = html.unescape(video_info.get("title", "未知标题"))
                pic = video_info.get("pic", "无封面")
                return title, pic
            else:
                logger.warning(f"Bilibili API returned error code: {data.get('code')}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching video info: {e}")
            return None