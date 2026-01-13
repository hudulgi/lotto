import base64
import random
import os
import time
import traceback
from io import BytesIO

from PIL import Image
from support import SupportDiscord
from tool import ToolNotify

from .ff_pylotto import DhLottery
from .model import ModelLottoItem
from .setup import *


class ModuleBasic(PluginModuleBase):

    def __init__(self, P):
        super(ModuleBasic, self).__init__(P, name='basic', first_menu='setting', scheduler_desc="로또 자동 구입")
        self.db_default = {
            f'db_version': '1',
            f'{self.name}_auto_start': 'False',
            f'{self.name}_interval': '0 8 * * *',
            f'{self.name}_db_delete_day': '30',
            f'{self.name}_db_auto_delete': 'False',
            f'{P.package_name}_item_last_list_option': '',

            f'driver_mode': 'remote',
            f'driver_local_headless': 'False',
            f'driver_remote_url': 'http://172.17.0.1:4444/wd/hub',
            f'user_id': '',
            f'user_passwd': '',
            f'charge_money': '20000',
            f'buy_data': '',
            f'notify_mode': 'always',
            f'buy_mode_one_of_week': 'True',
        }
        self.web_list_model = ModelLottoItem

    @staticmethod
    def _fmt_won(v):
        """
        예치금 표시용 포맷
        - 100000 -> '100,000원'
        - '100000' -> '100,000원'
        - None/'-'/기타 문자열 -> 그대로 반환(안전)
        """
        try:
            if v is None:
                return '-'

            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return '-'
                s = s.replace(',', '').replace('원', '').strip()
                if s.isdigit():
                    v = int(s)
                else:
                    return v

            if isinstance(v, float) and v.is_integer():
                v = int(v)

            if isinstance(v, int):
                return f"{v:,}원"

            return str(v)
        except Exception:
            return str(v)

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        if sub == 'setting':
            arg['is_include'] = F.scheduler.is_include(self.get_scheduler_name())
            arg['is_running'] = F.scheduler.is_running(self.get_scheduler_name())
        return render_template(f'{P.package_name}_{self.name}_{sub}.html', arg=arg)

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret': 'success'}
        if command == 'test_info' or command == 'test_buy':
            data = self.do_action(mode=command)
            if data.get('status') == 'fail':
                # 기존 코드가 data['data']를 참조해 KeyError가 날 수 있어 안전하게 처리
                ret['modal'] = d(data)
                ret['title'] = '에러'
                ret['data'] = data
            else:
                ret['modal'] = f"예치금 : {self._fmt_won(data.get('deposit'))}"
                ret['modal'] += f"\n이미 구입 : {data['history']['count']}건 (미추첨)"
                ret['modal'] += f"\n가능 : {data['available_count']}건"
                if 'buy' in data:
                    ret['modal'] += f"\n회차 : {data['buy']['round']}"
                ret['title'] = "테스트"
                ret['data'] = data
        return jsonify(ret)

    def scheduler_function(self):
        try:
            noti_mode = P.ModelSetting.get('notify_mode')
            notify = False
            ret = self.do_action()
            img_bytes = None
            img_url = None

            msg = '로또'
            msg += f"\n예치금 : {self._fmt_won(ret.get('deposit'))}"
            msg += f"\n구매가능 : {ret.get('available_count', '-')}"

            if ret.get('status') == 'NOT_AVAILABLE_COUNT':
                msg += "\n구매 가능 건수가 없어 종료"
            elif ret.get('status') == 'ALREADY_THIS_WEEK_BUY':
                msg += "\n이미 이번 주 구매"
            elif ret.get('status') == 'NOT_AVAILABLE_MONEY':
                msg += "\n예치금 부족으로 종료"
                if noti_mode == 'real_buy':
                    notify = True
            elif ret.get('status') == 'fail':
                msg += "\n실행 실패(fail)"
                if ret.get('log'):
                    msg += f"\n{str(ret.get('log'))[:800]}"
                if noti_mode in ('always',):
                    notify = True
            else:
                buy = ret.get('buy')
                if buy and isinstance(buy, dict):
                    msg += f"\n구매 수 : {len(buy.get('buy_list') or [])}"
                    msg += f"\n회차 : {buy.get('round', '-')}"
                else:
                    msg += "\n구매 정보 없음"

            buy = ret.get('buy')
            if buy and isinstance(buy, dict) and len(buy.get('buy_list') or []) > 0:
                img_bytes = base64.b64decode(buy['screen_shot'])
                filepath = os.path.join(F.config['path_data'], 'tmp', f"proxy_{str(time.time())}.png")
                img = Image.open(BytesIO(img_bytes))
                img.save(filepath)
                img_url = SupportDiscord.discord_proxy_image_localfile(filepath)

                if noti_mode == 'real_buy':
                    notify = True

                db_item = ModelLottoItem()
                db_item.round = buy.get('round')
                db_item.count = len(buy.get('buy_list') or [])
                db_item.data = ret
                db_item.img = img_url
                db_item.save()

            if noti_mode == 'always':
                notify = True
            elif noti_mode == 'none':
                notify = False

            if notify:
                ToolNotify.send_message(msg, 'lotto', image_url=img_url)
        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())

    def do_action(self, mode="buy"):
        lotto = None
        try:
            ret = {'status': None}
            lotto = DhLottery(P)
            lotto.driver_init(
                P.ModelSetting.get('driver_mode'),
                P.ModelSetting.get_bool('driver_local_headless'),
                P.ModelSetting.get('driver_remote_url')
            )
            lotto.login(P.ModelSetting.get('user_id'), P.ModelSetting.get('user_passwd'))

            ret['deposit'] = lotto.check_deposit()
            ret['deposit_before'] = ret['deposit']

            ret['history'] = lotto.check_history()
            stream = BytesIO(ret['history']['screen_shot'])
            img = Image.open(stream)
            img.save(stream, format='png')
            ret['history']['screen_shot'] = base64.b64encode(stream.getvalue()).decode()

            ret['available_count'] = 5 - ret['history']['count']
            if mode == 'test_info':
                return ret

            buy_data = self.get_buy_data()
            if ret['available_count'] == 0:
                ret['status'] = 'NOT_AVAILABLE_COUNT'
            elif P.ModelSetting.get_bool('buy_mode_one_of_week') and ret['available_count'] != 5:
                ret['status'] = 'ALREADY_THIS_WEEK_BUY'
            else:
                if min(len(buy_data), ret['available_count']) * 1000 > ret['deposit']:
                    ret['status'] = 'NOT_AVAILABLE_MONEY'

            if len(buy_data) > ret['available_count']:
                buy_data = buy_data[:ret['available_count']]

            if ret['status'] is None:
                if mode == 'test_buy':
                    ret['buy'] = lotto.buy_lotto(buy_data, dry=True)
                else:
                    ret['buy'] = lotto.buy_lotto(buy_data)

                stream = BytesIO(ret['buy']['screen_shot'])
                img = Image.open(stream)
                img.save(stream, format='png')
                ret['buy']['screen_shot'] = base64.b64encode(stream.getvalue()).decode()

                # 구매 성공 시 예치금 리프레시(차감 반영)
                try:
                    ret['deposit_after'] = lotto.check_deposit()
                    if isinstance(ret.get('deposit_after'), int):
                        ret['deposit'] = ret['deposit_after']
                except Exception:
                    pass

            return ret

        except Exception as e:
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())
            ret = {'status': 'fail'}
            ret['log'] = str(traceback.format_exc())
        finally:
            try:
                if lotto is not None:
                    lotto.driver_quit()
            except Exception:
                pass
        return ret

    @staticmethod
    def get_buy_data():
        def auto():
            ret = []
            while len(ret) < 6:
                tmp = str(random.randint(1, 45))
                if tmp not in ret:
                    ret.append(tmp)
            return ret

        data = P.ModelSetting.get_list('buy_data')
        ret = []
        plugin_auto = auto()
        for item in data:
            if item.startswith('plugin_auto'):
                ret.append(f"manual : {','.join(plugin_auto)}")
            else:
                ret.append(item)
        P.logger.info(d(ret))
        return ret
