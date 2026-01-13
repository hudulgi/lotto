import re
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
            options.set_preference(
                "general.useragent.override",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
            )
            options.set_preference("general.platform.override", "Win32")
            self.driver = webdriver.Remote(_host, options=options)

    def login(self, _uid, _passwd):
        # 로그인 페이지 이동 (신규 URL)
        self.driver.get('https://www.dhlottery.co.kr/login')

        # (신규 로그인 페이지 DOM 기준)
        WebDriverWait(self.driver, 10).until(lambda d: d.find_element(By.ID, "inpUserId"))
        self.driver.find_element(By.ID, "inpUserId").clear()
        self.driver.find_element(By.ID, "inpUserId").send_keys(_uid)          # 아이디
        self.driver.find_element(By.ID, "inpUserPswdEncn").clear()
        self.driver.find_element(By.ID, "inpUserPswdEncn").send_keys(_passwd) # 비밀번호

        # 로그인 버튼 클릭
        btn = self.driver.find_element(By.ID, "btnLogin")
        try:
            # firefox remote에서 가끔 click이 튕기는 케이스 방어
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            self.driver.execute_script("arguments[0].click();", btn)
        except Exception:
            btn.click()

        # 로그인 완료(로그인 페이지 이탈) 대기
        try:
            WebDriverWait(self.driver, 10).until(lambda d: '/login' not in (d.current_url or ''))
        except Exception:
            pass

        # 팝업이 뜨는 경우 닫기
        try:
            WebDriverWait(self.driver, 3).until(lambda d: len(d.window_handles) > 1)
            self.remove_popup()
        except Exception:
            pass

    def check_deposit(self):
        """
        신규 마이페이지(https://www.dhlottery.co.kr/mypage/home) 기준 예치금 파싱.
        가장 우선: #totalAmt(예치금 잔액 숫자) 직접 읽기.
        (fallback) JS/HTML 정규식 스캔.

        (최소 변경 추가)
        - #totalAmt 텍스트가 AJAX로 뒤늦게 갱신되는 케이스에서 '1' 등 임시값을 잡는 문제 방지:
          짧은 간격으로 연속 읽기하여 값이 2회 연속 동일할 때 확정(최대 6초).
        """
        _driver = self.driver
        _driver.get('https://www.dhlottery.co.kr/mypage/home')

        # 로그인 세션이 없으면 여기서 /login 또는 비슷한 흐름으로 이동할 수 있음
        if '/login' in (_driver.current_url or ''):
            raise RuntimeError("마이페이지 진입 실패: 로그인 세션이 유효하지 않습니다. (redirected to /login)")

        def _read_total_amt_text():
            try:
                el = _driver.find_element(By.ID, "totalAmt")
            except Exception:
                return None
            dep_txt = (el.text or "").strip()
            if not dep_txt:
                dep_txt = (el.get_attribute("textContent") or "").strip()
            if not dep_txt:
                return None
            dep_txt = dep_txt.replace(",", "").strip()
            if dep_txt.isdigit():
                return dep_txt
            return None

        # 0) 가장 확실: 예치금 숫자 스팬(id=totalAmt) 직접 파싱 (값 안정화)
        try:
            WebDriverWait(_driver, 10).until(lambda d: d.find_element(By.ID, "totalAmt"))

            last = None
            stable = 0
            t_end = time.time() + 6.0  # 최대 6초 동안 값 안정화 대기

            while time.time() < t_end:
                v = _read_total_amt_text()
                if v:
                    if v == last:
                        stable += 1
                    else:
                        last = v
                        stable = 0

                    # 2회 연속 동일(=3 정상 샘플 중 2번째부터) 시 확정
                    if stable >= 1:
                        return int(v)

                time.sleep(0.25)
        except Exception:
            pass

        # 1) JS로 '예치금 잔액' 블럭 주변에서 숫자 추출 (fallback)
        dep = None
        try:
            dep = _driver.execute_script(r"""
                function norm(s){ return (s||"").replace(/\s+/g," ").trim(); }
                function textOf(el){ return norm((el && (el.innerText || el.textContent)) || ""); }

                // 우선순위 1: #totalAmt가 있으면 그 값 사용
                const ta = document.querySelector("#totalAmt");
                if (ta) {
                  const v = norm(ta.textContent || ta.innerText || "");
                  if (v) return v;
                }

                // 우선순위 2: "예치금 잔액"이 포함된 컨테이너에서 숫자 추출
                const rx = /([0-9]{1,3}(?:,[0-9]{3})*)/;
                const keys = ["예치금 잔액"];

                const nodes = Array.from(document.querySelectorAll("body *"));
                for (const el of nodes) {
                    const t = textOf(el);
                    if (!t) continue;
                    if (!keys.some(k => t.includes(k))) continue;

                    // 예치금 잔액이 있는 el에서 부모 5단계까지 확장하며,
                    // "예치금 잔액" 텍스트 이후 구간에서만 숫자 매칭 시도
                    let p = el;
                    for (let i=0; i<6 && p; i++) {
                        const tp = textOf(p);
                        const idx = tp.indexOf("예치금 잔액");
                        if (idx >= 0) {
                            const tail = tp.slice(idx);
                            const m = tail.match(rx);
                            if (m) return m[1];
                        }
                        p = p.parentElement;
                    }
                }
                return null;
            """)
        except Exception:
            dep = None

        # 2) HTML 소스에서 정규식 추출(보조)
        if not dep:
            html = _driver.page_source or ""
            # totalAmt 기반 패턴(가능하면 우선)
            m = re.search(r'id=["\']totalAmt["\'][^>]*>\s*([0-9]{1,3}(?:,[0-9]{3})*)\s*<', html, re.IGNORECASE)
            if m:
                dep = m.group(1)
            else:
                m = re.search(r"예치금(?:\s*잔액)?[^0-9]{0,80}([0-9]{1,3}(?:,[0-9]{3})*)\s*원", html)
                if not m:
                    m = re.search(r"예치금[^0-9]{0,80}([0-9]{1,3}(?:,[0-9]{3})*)\s*원", html)
                if m:
                    dep = m.group(1)

        if not dep:
            raise RuntimeError("예치금 파싱 실패: 마이페이지 HTML에서 예치금 값을 찾지 못했습니다. (#totalAmt/텍스트/정규식 모두 실패)")

        dep = str(dep).replace(',', '').strip()
        return int(dep)

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

    def buy_lotto(self, buy_data, dry=False):
        """
        로또 구매 수행.

        Args:
            buy_data: 구매 정보 리스트. 'auto' 또는 'manual:1,2,3,4,5,6' 형식.
            dry: True면 구매 없이 번호 선택 화면만 캡처.

        Returns:
            dict: ret, round, buy_list, screen_shot, deposit_after 포함.
        """
        ret = {'ret': 'success', 'buy_list': []}

        # (신규) 바로구매 페이지로 직접 진입 (현재 DOM/구조 기준)
        self.driver.get('https://ol.dhlottery.co.kr/olotto/game/game645.do')

        # 라운드 확인
        ret['round'] = WebDriverWait(self.driver, 10).until(
            lambda d: d.find_element(By.ID, 'curRound').text
        )

        for item in buy_data:
            tmp = item.split(':')
            mode = tmp[0].strip()

            if mode == 'auto':  # 자동모드
                self.driver.find_element(By.CSS_SELECTOR, "label[for='checkAutoSelect']").click()

            elif mode == 'manual':  # 수동모드, 혼합모드
                nums = tmp[1].split(',')
                for _n in nums:
                    n = _n.strip()
                    if not n:
                        continue
                    self.driver.find_element(By.CSS_SELECTOR, f"label[for='check645num{n}']").click()
                if len([x for x in nums if x.strip()]) < 6:
                    self.driver.find_element(By.CSS_SELECTOR, "label[for='checkAutoSelect']").click()

            # 번호 적용(게임 추가)
            self.driver.find_element(By.ID, 'btnSelectNum').click()

        if dry:
            # dry run: 번호 지정된 화면만 캡처
            tag = self.driver.find_element(By.CLASS_NAME, 'selected-games')
            ret['screen_shot'] = tag.screenshot_as_png
            return ret

        # 구매하기
        self.driver.find_element(By.ID, 'btnBuy').click()

        # 최종 구매 확인(기존 JS 함수 유지되는지 확인됨)
        self.driver.execute_script("javascript:closepopupLayerConfirm(true);")

        # 구매 결과(선택번호) 로드 대기
        _res1 = WebDriverWait(self.driver, 10).until(
            lambda d: d.find_elements(By.XPATH, '//ul[@id="reportRow"]/li')
        )

        for _r1 in _res1:
            _selected = []
            _res2 = _r1.find_elements(By.XPATH, 'div[@class="nums"]/span')
            for _r2 in _res2:
                t = (_r2.text or "").strip()
                if t:
                    _selected.append(t)
            if _selected:
                ret['buy_list'].append(_selected)

        tag = self.driver.find_element(By.ID, 'popReceipt')
        ret['screen_shot'] = tag.screenshot_as_png

        # 구매 성공 후 예치금 재조회(차감 반영)
        try:
            ret['deposit_after'] = self.check_deposit()
        except Exception as e:
            ret['deposit_after'] = None
            ret['deposit_after_error'] = str(e)

        return ret

    def check_history(self):
        """
        구매/당첨 내역 확인 (신규 마이페이지 기준)

        핵심 수정(최소 변경):
        1) 검색 전에 '복권상품'을 로또645로 강제 선택(가능하면 '추첨식'도 강제)
           - 전체 조회로 인한 페이지네이션/비동기 재렌더링 변동을 줄여 Timeout/Stale 확률 감소
        2) '최근 1주일' 버튼 클릭 후 날짜값 변경을 짧게 대기(기존 유지)
        3) 검색 후, 결과 리스트(.whl-row) 또는 '데이터 없음' 상태가 확정될 때까지 대기
        4) ret['data']는 '로또645 + 구입매수(ea)>0'인 행을 결과와 무관하게 포함
        5) ret['count']는 기존과 동일하게 '미추첨'만 합산

        (최소 변경 추가)
        - 검색 직후 DOM이 흔들리는 구간에서 '데이터 없음'을 오판하거나 이전 결과를 읽는 케이스 방지:
          rows/no-data 상태가 짧게라도 "정착(settle)"할 때까지 추가 대기.
        """
        self.driver.get('https://www.dhlottery.co.kr/mypage/mylotteryledger')

        if '/login' in (self.driver.current_url or ''):
            raise RuntimeError("구매/당첨 내역 진입 실패: 로그인 세션이 유효하지 않습니다. (redirected to /login)")

        def _js_click(el):
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            except Exception:
                pass
            try:
                self.driver.execute_script("arguments[0].click();", el)
                return True
            except Exception:
                try:
                    el.click()
                    return True
                except Exception:
                    return False

        def _force_draw_type_to_lotto():
            """
            (가능하면) '추첨식' 라디오를 선택.
            로또645는 추첨식이므로, 즉석식/전체가 선택되어 있으면 결과가 섞일 수 있음.
            """
            try:
                # '추첨식' 텍스트를 가진 label 우선 클릭
                labels = self.driver.find_elements(By.XPATH, "//label[contains(normalize-space(.),'추첨식')]")
                for lb in labels:
                    if _js_click(lb):
                        time.sleep(0.2)
                        return True
            except Exception:
                pass

            # fallback: radio input 중 value/name 패턴이 있을 수 있어 전체 순회
            try:
                radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                for r in radios:
                    try:
                        rid = (r.get_attribute("id") or "").strip()
                        name = (r.get_attribute("name") or "").strip().lower()
                        val = (r.get_attribute("value") or "").strip()
                        if "draw" in name or "drw" in name or "gubun" in name or "type" in name:
                            # 라벨 텍스트 매칭
                            if rid:
                                lbs = self.driver.find_elements(By.CSS_SELECTOR, f"label[for='{rid}']")
                                for lb in lbs:
                                    t = (lb.text or "").strip()
                                    if "추첨식" in t:
                                        if _js_click(lb):
                                            time.sleep(0.2)
                                            return True
                        # value가 '1' 같은 케이스까지 무리하게 누르진 않음(오탐 방지)
                    except Exception:
                        continue
            except Exception:
                pass
            return False

        def _force_product_to_lotto645():
            """
            '복권상품' 드롭다운을 로또645로 강제.
            1) 표준 <select> 기반: 모든 select 순회 후 option 텍스트에 '로또645/로또 6/45'가 있으면 선택
            2) 실패 시: 아무 것도 하지 않고 진행(파싱에서 다시 로또645만 필터링)
            """
            target_keys = ["로또645", "로또 6/45", "로또6/45", "Lotto 6/45"]

            def _match_option_text(t: str) -> bool:
                tt = (t or "").strip()
                if not tt:
                    return False
                for k in target_keys:
                    if k in tt:
                        return True
                return False

            # 1) <select> 순회 후 로또645 옵션이 있는 select를 찾아 선택
            try:
                selects = self.driver.find_elements(By.TAG_NAME, "select")
                for sel in selects:
                    try:
                        opts = sel.find_elements(By.TAG_NAME, "option")
                        if not opts:
                            continue
                        # 옵션 중 로또645가 있는지 확인
                        hit_text = None
                        for o in opts:
                            ot = (o.text or "").strip()
                            if _match_option_text(ot):
                                hit_text = ot
                                break
                        if not hit_text:
                            continue

                        # 이 select가 복권상품일 확률이 높으므로 선택 시도
                        try:
                            Select(sel).select_by_visible_text(hit_text)
                            time.sleep(0.3)
                            return True
                        except Exception:
                            # 일부 페이지는 value로만 동작할 수 있어 value로도 시도
                            try:
                                for o in opts:
                                    ot = (o.text or "").strip()
                                    if ot == hit_text:
                                        val = (o.get_attribute("value") or "").strip()
                                        if val:
                                            Select(sel).select_by_value(val)
                                            time.sleep(0.3)
                                            return True
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass

            return False

        # 상세 검색 펼치기(있으면)
        try:
            tbtn = WebDriverWait(self.driver, 5).until(lambda d: d.find_element(By.ID, 'srchBtnToggle'))
            _js_click(tbtn)
            time.sleep(0.5)
        except Exception:
            pass

        # (추가) 추첨식 + 로또645로 조회 조건 강제
        try:
            _force_draw_type_to_lotto()
        except Exception:
            pass
        try:
            _force_product_to_lotto645()
        except Exception:
            pass

        # 날짜 input 확보 (없으면 이후 클릭/검색만 시도)
        before_str = None
        before_end = None
        try:
            str_el = WebDriverWait(self.driver, 5).until(lambda d: d.find_element(By.ID, 'srchStrDt'))
            end_el = WebDriverWait(self.driver, 5).until(lambda d: d.find_element(By.ID, 'srchEndDt'))
            before_str = (str_el.get_attribute("value") or "").strip()
            before_end = (end_el.get_attribute("value") or "").strip()
        except Exception:
            str_el = None
            end_el = None

        # '최근 1주일' 강제 클릭 (onclick: fn_chgDt(event, '2'))
        clicked_week = False
        try:
            week_btn = WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "button.btChgDt[onclick*=\"fn_chgDt\"][onclick*=\"'2'\"]")
            )
            clicked_week = _js_click(week_btn)
        except Exception:
            # XPath fallback
            try:
                week_btn = WebDriverWait(self.driver, 5).until(
                    lambda d: d.find_element(
                        By.XPATH,
                        "//button[contains(@class,'btChgDt') and contains(@onclick,'fn_chgDt') and contains(@onclick,\"'2'\")]"
                    )
                )
                clicked_week = _js_click(week_btn)
            except Exception:
                clicked_week = False

        # 클릭이 성공했다면 날짜 값 변경을 조금 기다림
        if clicked_week and (str_el is not None) and (end_el is not None) and (before_str or before_end):
            try:
                def _changed(d):
                    try:
                        s = (d.find_element(By.ID, "srchStrDt").get_attribute("value") or "").strip()
                        e = (d.find_element(By.ID, "srchEndDt").get_attribute("value") or "").strip()
                        return (s != (before_str or "")) or (e != (before_end or ""))
                    except Exception:
                        return False

                WebDriverWait(self.driver, 5).until(_changed)
            except Exception:
                pass

        # 검색 버튼 클릭(있으면)
        try:
            sbtn = WebDriverWait(self.driver, 5).until(lambda d: d.find_element(By.ID, 'btnSrch'))
            _js_click(sbtn)
        except Exception:
            pass

        ret = {'count': 0, 'data': []}

        # 결과 컨테이너 확보 + 결과 갱신 대기
        def _get_container():
            return self.driver.find_element(By.ID, 'winning-history-list')

        def _rows_count():
            try:
                c = _get_container()
                return len(c.find_elements(By.CSS_SELECTOR, ".whl-body .whl-row"))
            except Exception:
                return 0

        def _no_data_text_hit(t: str) -> bool:
            tt = (t or "").strip()
            if not tt:
                return False
            # 흔한 문구들(정확 문구가 다를 수 있어 핵심 키만)
            if ("내역" in tt and "없" in tt) or ("조회" in tt and "없" in tt) or ("데이터" in tt and "없" in tt):
                return True
            return False

        def _is_no_data():
            """
            사이트가 '데이터 없음'을 어떤 방식으로 표기하는지 확실치 않아
            텍스트 기반으로 넓게 감지하되, rows가 0일 때만 no-data로 판정(오탐 감소).
            """
            try:
                if _rows_count() > 0:
                    return False
                c = _get_container()
                t = (c.text or "").strip()
                return _no_data_text_hit(t)
            except Exception:
                pass
            return False

        try:
            WebDriverWait(self.driver, 10).until(lambda d: _rows_count() > 0 or _is_no_data())
            container = _get_container()
        except Exception:
            # 컨테이너/결과를 못 잡으면 최소한 화면 캡처라도 남김
            try:
                ret['screen_shot'] = self.driver.find_element(By.TAG_NAME, "body").screenshot_as_png
            except Exception:
                pass
            return ret

        # (추가) 검색 직후 DOM 흔들림 정착 대기(최대 6초)
        try:
            t_end = time.time() + 6.0
            last_sig = None
            stable = 0

            while time.time() < t_end:
                rc = _rows_count()
                nd = _is_no_data()
                try:
                    c = _get_container()
                    txt = (c.text or "")
                except Exception:
                    txt = ""
                sig = (rc, nd, (txt[:200] if txt else ""))

                if sig == last_sig:
                    stable += 1
                else:
                    last_sig = sig
                    stable = 0

                # 2회 연속 동일(=안정화) 시 종료
                if stable >= 1:
                    break

                time.sleep(0.4)

            container = _get_container()
        except Exception:
            pass

        # 행 파싱
        rows = container.find_elements(By.CSS_SELECTOR, ".whl-body .whl-row")
        for row in rows:
            def safe_text(sel):
                try:
                    return (row.find_element(By.CSS_SELECTOR, sel).text or "").strip()
                except Exception:
                    return ""

            col_date1 = safe_text(".whl-col.col-date1")
            col_name  = safe_text(".whl-col.col-name")
            col_round = safe_text(".whl-col.col-th")
            col_nums  = safe_text(".whl-col.col-num")
            col_ea    = safe_text(".whl-col.col-ea")
            col_res   = safe_text(".whl-col.col-result")
            col_prize = safe_text(".whl-col.col-am")
            col_date2 = safe_text(".whl-col.col-date2")

            # 구입매수 숫자 추출
            m_ea = re.search(r"(\d+)", (col_ea or "").replace(",", ""))
            ea = int(m_ea.group(1)) if m_ea else 0

            # 로또645 판단 (표기 흔들림 방어)
            name_txt = (col_name or "")
            is_lotto645 = ("로또" in name_txt) and (("645" in name_txt) or ("6/45" in name_txt))

            # data는 결과와 무관하게 포함 (단, 로또645 + ea>0 조건)
            if is_lotto645 and ea > 0:
                data_row = [
                    col_date1,     # 0
                    col_name,      # 1
                    col_round,     # 2
                    col_nums,      # 3
                    str(ea),       # 4 (구입매수)
                    col_res,       # 5 (결과: 미추첨/당첨/낙첨 등)
                    col_prize,     # 6
                    col_date2,     # 7
                ]
                ret['data'].append(data_row)

                # 한도 계산용 count는 '미추첨'만 합산
                if "미추첨" in (col_res or ""):
                    ret['count'] += ea

        # 화면 캡처(신규 컨테이너)
        try:
            ret['screen_shot'] = container.screenshot_as_png
        except Exception:
            try:
                ret['screen_shot'] = self.driver.find_element(By.TAG_NAME, "body").screenshot_as_png
            except Exception:
                pass

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