import threading
import time
import traceback

from selenium import webdriver
from selenium.common.exceptions import UnexpectedAlertPresentException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


class DhLottery:
    """
    동행복권(dhlottery.co.kr) 로또 자동 구매 클래스

    Selenium을 이용하여 동행복권 사이트에서 로또 6/45를 자동으로 구매한다.
    로컬 Chrome 또는 원격 Firefox 드라이버를 지원한다.
    """

    def __init__(self, P):
        """
        Args:
            P: 로거(logger) 속성을 포함한 부모 객체
        """
        self.P = P
        self.driver = None

    def driver_init(self, mode='local', headless=False, host=None):
        """
        웹드라이버 초기화

        Args:
            mode: 'local' (로컬 Chrome) 또는 'remote' (원격 Firefox)
            headless: True면 브라우저 창 없이 실행
            host: remote 모드일 때 Selenium Grid 호스트 주소
        """
        if mode == 'local':
            # 로컬 Chrome 드라이버 사용
            from selenium.webdriver.chrome.options import Options
            options = Options()
            if headless:
                options.add_argument('headless')
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
        elif mode == 'remote':
            # 원격 Firefox 드라이버 사용 (Windows Chrome UA로 위장)
            from selenium.webdriver.firefox.options import Options
            options = Options()
            options.set_preference(
                "general.useragent.override",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/107.0.0.0 Safari/537.36"
            )
            options.set_preference("general.platform.override", "Win32")
            self.driver = webdriver.Remote(host, options=options)

    def login(self, uid, passwd):
        """
        동행복권 사이트 로그인

        Args:
            uid: 사용자 아이디
            passwd: 비밀번호
        """
        self.driver.get('https://www.dhlottery.co.kr/login')
        self.driver.find_element(By.XPATH, '//input[@id="inpUserId"]').send_keys(uid)
        self.driver.find_element(By.XPATH, '//input[@id="inpUserPswdEncn"]').send_keys(passwd)
        self.driver.find_element(By.XPATH, '//button[@id="btnLogin"]').click()

    def check_deposit(self):
        """
        예치금 잔액 확인

        Returns:
            int: 현재 예치금 잔액 (원 단위)
        """
        self.driver.get('https://www.dhlottery.co.kr/mypage/home')
        # 비동기로 로드되는 예치금 금액을 대기 (숫자가 포함될 때까지)
        deposit = WebDriverWait(self.driver, 10).until(
            lambda d: (t := d.find_element(By.XPATH, '//div[@id="divCrntEntrsAmt"]').text.strip())
                      and any(c.isdigit() for c in t) and t
        )
        deposit = deposit.replace(',', '').replace('원', '')
        return int(deposit)

    def buy_lotto(self, buy_data, dry=False):
        """
        로또 구매

        Args:
            buy_data: 구매할 번호 리스트
                - 'auto': 자동 선택
                - 'manual:1,2,3,4,5,6': 수동 선택 (6개 번호 지정)
                - 'manual:1,2,3': 반자동 (일부 번호 지정, 나머지 자동)
            dry: True면 실제 구매 없이 선택 화면만 캡처 (테스트용)

        Returns:
            dict: 구매 결과
                - ret: 'success' 또는 'fail'
                - round: 회차 번호
                - buy_list: 구매된 번호 목록 (각 게임별 6개 번호)
                - screen_shot: 결과 화면 스크린샷 (PNG bytes)
                - log: 실패 시 에러 메시지
        """
        ret = {'ret': 'success', 'buy_list': []}
        self.driver.get('https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LO40')

        # 게임 iframe으로 전환
        try:
            iframe = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "ifrm_tab"))
            )
            self.driver.switch_to.frame(iframe)
        except UnexpectedAlertPresentException as e:
            # 판매 시간 외 등의 알림이 뜨는 경우
            ret['ret'] = 'fail'
            ret['log'] = e.alert_text
            return ret

        # 현재 회차 번호 가져오기
        ret['round'] = WebDriverWait(self.driver, 5).until(
            lambda d: d.find_element(By.ID, 'curRound')
        ).text

        # 각 게임별로 번호 선택
        for item in buy_data:
            parts = item.split(':')
            mode = parts[0].strip()

            if mode == 'auto':
                # 자동 선택
                self.driver.find_element(By.XPATH, '//label[@for="checkAutoSelect"]').click()
            elif mode == 'manual':
                # 수동/반자동 선택
                nums = parts[1].split(',')
                for n in nums:
                    self.driver.find_element(
                        By.XPATH, f'//label[@for="check645num{n.strip()}"]'
                    ).click()
                # 6개 미만 선택 시 나머지는 자동으로 채움
                if len(nums) < 6:
                    self.driver.find_element(By.XPATH, '//label[@for="checkAutoSelect"]').click()

            # 선택 확인 버튼 클릭
            self.driver.find_element(By.XPATH, '//input[@id="btnSelectNum"]').click()

        # dry run: 실제 구매 없이 선택 화면만 캡처
        if dry:
            tag = self.driver.find_element(By.CLASS_NAME, 'selected-games')
            ret['screen_shot'] = tag.screenshot_as_png
            return ret

        # 구매 버튼 클릭
        self.driver.find_element(By.XPATH, '//button[@id="btnBuy"]').click()
        # 최종 구매 확인 팝업 승인
        self.driver.execute_script("javascript:closepopupLayerConfirm(true);")

        # 구매 결과 대기
        rows = WebDriverWait(self.driver, 5).until(
            lambda d: d.find_elements(By.XPATH, '//ul[@id="reportRow"]/li')
        )

        # 구매된 번호들 추출
        for row in rows:
            selected = [span.text for span in row.find_elements(By.XPATH, 'div[@class="nums"]/span')]
            ret['buy_list'].append(selected)

        # 결과 화면 스크린샷
        ret['screen_shot'] = self.driver.find_element(By.ID, 'popReceipt').screenshot_as_png
        self.driver.switch_to.default_content()
        return ret

    def check_history(self):
        """
        최근 1주일 구매내역 확인

        Returns:
            dict: 구매내역 결과
                - count: 미추첨 로또 총 게임 수
                - data: 미추첨 항목 리스트 (name, result, count)
                - screen_shot: 내역 화면 스크린샷 (PNG bytes)
        """
        self.driver.get('https://www.dhlottery.co.kr/mypage/mylotteryledger')

        # 검색 조건 토글 버튼 클릭
        btn_toggle = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "srchBtnToggle"))
        )
        self.driver.execute_script("arguments[0].click();", btn_toggle)

        # "최근 1주일" 기간 선택
        btn_week = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((
                By.XPATH,
                '//button[contains(@onclick, "fn_chgDt") and contains(text(), "최근 1주일")]'
            ))
        )
        self.driver.execute_script("arguments[0].click();", btn_week)

        # 조회 버튼 클릭
        btn_search = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, 'btnSrch'))
        )
        self.driver.execute_script("arguments[0].click();", btn_search)

        ret = {'count': 0, 'data': []}

        # 결과 로드 대기
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((
                By.XPATH,
                '//ul[@class="whl-body"]/li[contains(@class, "whl-row")]'
            ))
        )

        # JavaScript로 데이터 추출 (Stale Element 방지)
        items = self.driver.execute_script('''
            const items = [];
            document.querySelectorAll('ul.whl-body li.whl-row').forEach(li => {
                const name = li.querySelector('.col-name .whl-txt')?.textContent?.trim() || '';
                const result = li.querySelector('.col-result .winResult')?.textContent?.trim() || '';
                const count = li.querySelector('.col-ea .whl-txt')?.textContent?.trim() || '0';
                items.push({name: name, result: result, count: parseInt(count) || 0});
            });
            return items;
        ''')

        # 로또645 중 미추첨 항목만 필터링
        for item in items:
            if item['name'] == '로또645' and item['result'] == '미추첨':
                ret['data'].append(item)
                ret['count'] += item['count']

        ret['screen_shot'] = self.driver.find_element(By.XPATH, '//ul[@class="whl-body"]').screenshot_as_png
        return ret

    def driver_quit(self):
        """
        드라이버 종료

        별도 스레드에서 비동기로 종료하여 메인 스레드 블로킹 방지
        """
        if self.driver is not None:
            def quit_async():
                self.driver.quit()
                self.driver = None
                self.P.logger.debug('driver quit..')
            thread = threading.Thread(target=quit_async, daemon=True)
            thread.start()