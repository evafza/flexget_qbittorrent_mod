import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

from loguru import logger

from ..schema.nexusphp import NexusPHP
from ..schema.site_base import SignState
from ..schema.site_base import SiteBase
from ..utils.baidu_ocr import BaiduOcr

try:
    from PIL import Image
except ImportError:
    Image = None

# auto_sign_in
BASE_URL = 'https://open.cd/'
URL = 'https://open.cd/plugin_sign-in.php'
SUCCEED_REGEX = '查看簽到記錄|{"state":"success","signindays":"\\d+","integral":"\\d+"}'
WRONG_REGEX = '验证码错误'

# html_rss
ROOT_ELEMENT_SELECTOR = '#form_torrent > table > tbody > tr:not(:first-child)'
FIELDS = {
    'title': {
        'element_selector': 'a[href*="details.php"]',
        'attribute': 'title'
    },
    'url': {
        'element_selector': 'a[href*="download.php"]',
        'attribute': 'href'
    },
    'promotion': {
        'element_selector': 'div[style="padding-bottom: 5px"] > img',
        'attribute': 'alt'
    },
    'progress': {
        'element_selector': '.progress_completed',
        'attribute': 'class'
    }
}


class MainClass(NexusPHP):
    @staticmethod
    def build_sign_in(entry, config):
        SiteBase.build_sign_in_entry(entry, config, URL, SUCCEED_REGEX, base_url=BASE_URL,
                                     wrong_regex=WRONG_REGEX)

    @staticmethod
    def build_html_rss_config(config):
        config['root_element_selector'] = ROOT_ELEMENT_SELECTOR
        config['fields'] = FIELDS

    def sign_in(self, entry, config):
        if not Image:
            entry.fail_with_prefix('Dependency does not exist: [PIL]')
            logger.warning('Dependency does not exist: [PIL]')
            return
        entry['base_response'] = base_response = self._request(entry, 'get', BASE_URL)
        sign_in_state, base_content = self.check_sign_in_state(entry, base_response, BASE_URL)
        if sign_in_state != SignState.NO_SIGN_IN:
            return

        image_hash_response = self._request(entry, 'get', URL)
        image_hash_state = self.check_net_state(entry, image_hash_response, URL)
        if image_hash_state:
            return
        image_hash_content = self._decode(image_hash_response)
        image_hash_re = re.search('(?<=imagehash=).*?(?=")', image_hash_content)
        img_src_re = re.search('(?<=img src=").*?(?=")', image_hash_content)

        if image_hash_re and img_src_re:
            image_hash = image_hash_re.group()
            img_src = img_src_re.group()
            img_url = urljoin(URL, img_src)
            img_response = self._request(entry, 'get', img_url)
            img_net_state = self.check_net_state(entry, img_response, img_url)
            if img_net_state:
                return
        else:
            entry.fail_with_prefix('Cannot find key: image_hash')
            return

        img = Image.open(BytesIO(img_response.content))
        code, img_byte_arr = BaiduOcr.get_ocr_code(img, entry, config)
        if not entry.failed:
            if len(code) == 6:
                params = {
                    'cmd': 'signin'
                }
                data = {
                    'imagehash': (None, image_hash),
                    'imagestring': (None, code)
                }
                response = self._request(entry, 'post', URL, files=data, params=params)
                final_state = self.final_check(entry, response, response.request.url)
            if len(code) != 6 or final_state == SignState.WRONG_ANSWER:
                code_file = Path('opencd.png')
                code_file.write_bytes(img_byte_arr)
                entry.fail_with_prefix('ocr failed: {}, see opencd.png'.format(code))

    def build_selector(self):
        selector = super(MainClass, self).build_selector()
        self.dict_merge(selector, {
            'detail_sources': {
                'default': {
                    'elements': {
                        'bar': '#info_block > tbody > tr > td > table > tbody > tr > td:nth-child(2)'
                    }
                }
            }
        })
        return selector
