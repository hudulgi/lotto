import threading
import time
import traceback

from selenium import webdriver
from selenium.common.exceptions import UnexpectedAlertPresentException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


class DhLottery:
    def __init__(self, P):
        self.P = P
        self.driver = None

    def driver_init(self, _mode='local', _headless=False, _host=None):
        if _mode == 'local':
            from selenium.webdriver.chrome.options import Options
            options = Options()
            if _headless:
                options.add_argument('headless')
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        elif _mode == 'remote':
            from selenium.webdriver.firefox.options import Options
            options = Options()
            options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                                 "Chrome/107.0.0.0 Safari/537.36")
            options.set_preference("general.platform.override", "Win32")
            self.driver = webdriver.Remote(_host, options=options)

    def login(self, _uid, _passwd):
        # 로그인 페이지 이동
        self.driver.get('https://dhlottery.co.kr/user.do?method=login&returnUrl=')

        self.driver.find_element(By.XPATH, '//input[@name="userId"]').send_keys(_uid)  # 아이디 입력
        self.driver.find_element(By.XPATH, '//input[@name="password"]').send_keys(_passwd)  # 비밀번호 입력
        self.driver.execute_script("javascript:check_if_Valid3();")  # 로그인 실행

        try:
            WebDriverWait(self.driver, 3).until(lambda driver: len(driver.window_handles) > 1)
            self.remove_popup()  # 팝업창 제거함수 호출
        except:
            pass  

    def check_deposit(self):
        # 마이페이지로 이동
        _driver = self.driver
        _driver.get(url='https://dhlottery.co.kr/userSsl.do?method=myPage')

        # 예치금 금액 읽음
        _deposit = WebDriverWait(self.driver, 10)\
            .until(lambda driver: driver.find_element(By.XPATH, '//p[@class="total_new"]/strong').text)
        _deposit = _deposit.replace(',', '')  # 천단위 쉼표 제거
        return int(_deposit)

    def remove_popup(self):
        _driver = self.driver

        # 생성된 팝업창을 모두 닫음
        _tabs = _driver.window_handles
        while len(_tabs) != 1:
            _driver.switch_to.window(_tabs[1])
            _driver.close()
            _tabs = _driver.window_handles

        # 첫 창으로 돌아간다
        _driver.switch_to.window(_tabs[0])

    '''
    @staticmethod
    def send_message(_msg):
        _msg = '<로또>\n' + _msg
        from tool import ToolNotify
        ToolNotify.send_message(_msg, "lotto",)

    def send_result(self, _data):
        _msg = '구매성공!!\n' + '=' * 15
        for _d in _data:
            _msg = _msg + '\n' + ','.join(_d)
        print(_msg)
        self.send_message(_msg)
    '''

    def buy_lotto(self, buy_data, dry=False):
        ret = {'ret': 'success', 'buy_list': []}
        # 메인 페이지로 이동
        self.driver.get('https://dhlottery.co.kr/common.do?method=main')

        # 팝업창 닫음
        try:
            WebDriverWait(self.driver, 3).until(lambda driver: len(driver.window_handles) > 1)
            self.remove_popup()  # 팝업창 제거함수 호출
        except:
            pass

        # 로또 구매 페이지로 이동
        self.driver.execute_script('javascript:goLottoBuy(2);')

        # 생성된 구매 페이지로 전환
        WebDriverWait(self.driver, 3).until(lambda driver: len(driver.window_handles) > 1)
        self.driver.switch_to.window(self.driver.window_handles[1])

        try:
            # 내부 iframe으로 전환
            self.driver.switch_to.frame(self.driver.find_element(By.TAG_NAME, "iframe"))
        except UnexpectedAlertPresentException as e:
            ret['ret'] = 'fail'
            ret['log'] = e.alert_text
            return ret

        ret['round'] = WebDriverWait(self.driver, 5).until(lambda driver: driver.find_element(By.ID, 'curRound')).text

        for item in buy_data:
            tmp = item.split(':')
            mode = tmp[0].strip()

            if mode == 'auto':  # 자동모드
                self.driver.find_element(By.XPATH, '//label[@for="checkAutoSelect"]').click()

            elif mode == 'manual':  # 수동모드, 혼합모드 (숫자 일부 지정, 나머지 자동)
                nums = tmp[1].split(',')
                for _n in nums:
                    self.driver.find_element(By.XPATH, f'//label[@for="check645num{_n.strip()}"]').click()
                if len(nums) < 6:
                    self.driver.find_element(By.XPATH, '//label[@for="checkAutoSelect"]').click()

            # 수량 변경
            #_select = Select(_driver.find_element(By.XPATH, '//select[@id="amoundApply"]'))
            #_select.select_by_value(str(_amount))

            # 수량 입력 확인
            self.driver.find_element(By.XPATH, '//input[@id="btnSelectNum"]').click()

        if dry:
            #  dry run, 구매 번호 지정된 화면만 캡쳐 후 종료
            tag = self.driver.find_element(By.CLASS_NAME, 'selected-games')
            ret['screen_shot'] = tag.screenshot_as_png
            return ret

        # 구매하기 버튼
        self.driver.find_element(By.XPATH, '//input[@id="btnBuy"]').click()

        # 최종 구매 확인
        self.driver.execute_script("javascript:closepopupLayerConfirm(true);")

        # 구매 번호 불러옴
        #time.sleep(3)
        #_res1 = self.driver.find_elements(By.XPATH, '//ul[@id="reportRow"]/li')
        _res1 = WebDriverWait(self.driver, 5).\
            until(lambda driver: driver.find_elements(By.XPATH, '//ul[@id="reportRow"]/li'))

        # 구매된 번호들을 인식
        for _r1 in _res1:
            _selected = list()
            _res2 = _r1.find_elements(By.XPATH, 'div[@class="nums"]/span')
            for _r2 in _res2:
                _selected.append(_r2.text)
            ret['buy_list'].append(_selected)

        tag = self.driver.find_element(By.ID, 'popReceipt')
        ret['screen_shot'] = tag.screenshot_as_png 

        # iframe에서 기본 창으로 다시 변경
        self.driver.switch_to.default_content()
        return ret

    # 구매내역 확인
    def check_history(self):
        self.driver.get('https://dhlottery.co.kr/myPage.do?method=lottoBuyListView')
        self.driver.execute_script("javascript:changeTerm( 7, '1주일');")
        self.driver.find_element(By.ID, 'submit_btn').click()

        ret = {'count': 0, 'data': []}
        frame_tag = self.driver.find_element(By.ID, "lottoBuyList")
        self.driver.switch_to.frame(frame_tag)
        for tr in self.driver.find_elements(By.XPATH, '/html/body/table/tbody/tr'):
            data = [x.text for x in tr.find_elements(By.TAG_NAME, 'td')]
            if len(data) == 1:  # 조회 결과가 없습니다.
                break
            if data[1] == '로또6/45' and data[5] == '미추첨':
                ret['data'].append(data)
                ret['count'] += int(data[4])
        self.driver.switch_to.default_content()

        ret['screen_shot'] = frame_tag.screenshot_as_png
        return ret

    def driver_quit(self):
        if self.driver is not None:
            def func():
                self.driver.quit()
                self.driver = None
                self.P.logger.debug('driver quit..')
            th = threading.Thread(target=func, args=())
            th.setDaemon(True)
            th.start()
            