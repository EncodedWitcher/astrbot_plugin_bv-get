from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
import astrbot.api.message_components as Comp
from astrbot.core.star.filter.permission import PermissionType
from astrbot.api.all import *

import re
import json
import urllib.request
from urllib.parse import urlparse
from urllib.error import URLError, HTTPError
import html

@register("bv-get", "YourName", "bv号获取插件", "1.0.1")
class BvPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        self.timeout = 10
        self.bv_pattern = re.compile(r'BV1[A-Za-z0-9]{9}')

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def bv_get(self, event: AstrMessageEvent):
        """获取链接后解析"""  # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        message = event.get_messages()  # 用户发的纯文本消息字符串
        bv_id = self.get_from_msg(message)
        if bv_id:
            result = self.get_bilibili_video_info(bv_id)
            if result:  # 避免 None 被解包
                title, pic = result
                chain=[
                    Comp.Plain(f'{bv_id}\n标题: {title[0]}\n'),
                    Comp.Image.fromURL(pic)
                ]
                yield event.chain_result(chain)
        else:
            pass


    def extract_bv(self, url):
        """
        从给定的Bilibili链接或b23.tv短链接中提取BV号
        :param url: 分享链接字符串
        :return: 提取到的BV号（大小写敏感），如果没有找到则返回None
        """
        if not url:
            return None
        final_url = self._resolve_short_url(url)
        return self._extract_bv_from_url(final_url)

    def _resolve_short_url(self, url):
        """
        解析b23.tv短链接，返回最终重定向的URL
        """
        match = re.search(r"https?://[^\s]+", url)
        if match:
            clean_url = match.group(0)
        else:
            return url
        parsed = urlparse(clean_url)
        if self._is_b23_link(parsed.netloc):
            try:
                req = urllib.request.Request(clean_url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return response.geturl()
            except HTTPError as e:
                print(f"HTTP错误({e.code}): {e.reason}")
            except URLError as e:
                print(f"URL错误: {e.reason}")
            except TimeoutError:
                print("短链接解析超时")
            return url

        return url

    def _is_b23_link(self, netloc):
        """判断是否是b23短链接域名"""
        return netloc in {'b23.tv', 'www.b23.tv'} or netloc.endswith('.b23.tv')

    def _extract_bv_from_url(self, url):
        """从URL字符串中提取BV号"""
        match = self.bv_pattern.search(url)
        return match.group() if match else None

    def check_bv_validity(self, bv_id):
        """
        检测提取出的BV号是否有效
        :param bv_id: 提取到的BV号
        :return: 如果有效返回True，否则返回False
        """
        if not bv_id:
            return False

        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
        try:
            req = urllib.request.Request(api_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data.get('code', -1) == 0
        except HTTPError as e:
            print(f"HTTP错误({e.code}): {e.reason}")
        except URLError as e:
            print(f"URL错误: {e.reason}")
        except TimeoutError:
            print("API 请求超时")
        except json.JSONDecodeError:
            print("JSON 解析错误")

        return False  # 默认返回无效

    def extract_bilibili_shortlink(self, msg_list):
        """
        从消息列表中提取 b23 链接
        """
        for msg in msg_list:
            if getattr(msg, "type", "") == "Json":
                cq_json_str = msg.data
                match = re.search(r'\[CQ:json,data=(.*?)\]', cq_json_str)
                if not match:
                    json_str = cq_json_str
                else:
                    json_str = match.group(1)

                json_str = html.unescape(json_str)

                try:
                    data = json.loads(json_str)
                    bilibili_url = data.get("meta", {}).get("detail_1", {}).get("qqdocurl") \
                                   or data.get("meta", {}).get("news", {}).get("jumpUrl")
                    return bilibili_url
                except (json.JSONDecodeError, KeyError):
                    continue  # 当前消息解析失败，继续尝试下一个
        return None

    def get_from_msg(self, msg_list):
        # 先尝试从 Json 类型中提取 URL
        bili_url = self.extract_bilibili_shortlink(msg_list)
        if bili_url:
            try:
                return self.extract_bv(bili_url)
            except Exception:
                return None

        # 如果没有 json 内容，就尝试在纯文本中找 BV 号或链接
        for msg in msg_list:
            if getattr(msg, "type", "") == "Plain":
                text = msg.text
                # 直接找BV号
                match = self.bv_pattern.search(text)
                if match:
                    return match.group()
                # 尝试从 URL 提取
                urls = re.findall(r'https?://[^\s]+', text)
                for url in urls:
                    try:
                        bv = self.extract_bv(url)
                        if bv:
                            return bv
                    except Exception:
                        continue
        return None

    def get_bilibili_video_info(self, bv_id):
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request) as response:
                data = json.loads(response.read().decode("utf-8"))

            # 检查 API 响应
            if data.get("code") == 0:
                video_info = data.get("data", {})
                title = video_info.get("title", "未知标题"),
                pic = video_info.get("pic", "无封面")
                # c_data = f">{bv_id}>\n>标题:{title[0]}>\n>[{pic}]"
                return title, pic
            else:
                return None

        except urllib.error.URLError as e:
            return None





