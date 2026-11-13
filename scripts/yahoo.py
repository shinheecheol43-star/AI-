"""Yahoo Finance 공용 세션 (쿠키 + crumb)."""
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class Yahoo:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.crumb = None

    def _auth(self):
        self.s.get("https://fc.yahoo.com", timeout=15)
        r = self.s.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=15)
        self.crumb = r.text.strip()

    def get(self, url, params=None, retries=5):
        for i in range(retries):
            try:
                r = self.s.get(url, params=params, timeout=30)
                if r.status_code == 429:
                    time.sleep(5 * (i + 1))
                    continue
                return r
            except requests.RequestException:
                time.sleep(2 * (i + 1))
        return None

    def screener(self, operands, size=250, offset=0):
        if not self.crumb:
            self._auth()
        body = {"size": size, "offset": offset, "sortField": "intradaymarketcap",
                "sortType": "DESC", "quoteType": "EQUITY",
                "query": {"operator": "AND", "operands": operands}}
        for i in range(5):
            r = self.s.post("https://query2.finance.yahoo.com/v1/finance/screener",
                            params={"crumb": self.crumb, "lang": "en-US",
                                    "region": "US", "formatted": "false"},
                            json=body, timeout=30)
            if r.status_code == 200:
                return r.json()["finance"]["result"][0]
            if r.status_code == 401:
                self._auth()
            time.sleep(3 * (i + 1))
        raise RuntimeError(f"screener failed: {r.status_code} {r.text[:200]}")
