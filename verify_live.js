const { chromium } = require('playwright');
const path = require('path');

// The container's egress policy blocks jma.go.jp and code4fukui.github.io, so the
// live code paths would otherwise ship untested. Intercept those requests and serve
// fixtures in the exact formats confirmed against the real endpoints:
//   amedastable.json  -> lat/lon as [degrees, minutes] pairs
//   map/<stamp>.json  -> every field as [value, qualityFlag]
//   all-cnt.csv       -> day,count
const AMEDAS_TABLE = {
  // Real-format entries near the Fukui nodes. lat/lon are [deg, min], as JMA ships them.
  "57066": { type: "A", kjName: "福井",   lat: [36, 3.3],  lon: [136, 13.4] },
  "57051": { type: "C", kjName: "三国",   lat: [36, 13.0], lon: [136, 8.9]  },
  "57091": { type: "C", kjName: "勝山",   lat: [36, 3.6],  lon: [136, 30.1] },
  "57121": { type: "C", kjName: "大野",   lat: [35, 58.9], lon: [136, 29.4] },
  "57046": { type: "C", kjName: "春江",   lat: [36, 10.6], lon: [136, 14.0] },
  "57246": { type: "A", kjName: "美浜",   lat: [35, 36.4], lon: [135, 56.9] },
  "99999": { type: "C", kjName: "遠い島", lat: [26, 0.0],  lon: [127, 0.0]  }, // must never win
};
const AMEDAS_OBS = {
  "57066": { temp: [21.4, 0], precipitation24h: [3.5, 0], wind: [2.8, 0], humidity: [78, 0] },
  "57051": { temp: [20.9, 0], precipitation24h: [6.0, 0], wind: [7.2, 0] },
  "57091": { temp: [19.1, 0], precipitation24h: [1.0, 0], wind: [1.9, 0], snow: [0, 0] },
  "57121": { temp: [18.6, 0], precipitation24h: [2.5, 0], wind: [1.4, 0], snow: [0, 0] },
  "57046": { temp: [21.0, 0], precipitation24h: [4.0, 0], wind: [3.3, 0] },
  "57246": { temp: [22.7, 0], precipitation24h: [8.5, 0], wind: [5.1, 0] },
  "99999": { temp: [31.0, 0], precipitation24h: [0.0, 0], wind: [9.9, 0] },
};
const FORECAST = [{ publishingOffice: "福井地方気象台", reportDatetime: "2026-09-09T11:00:00+09:00",
  timeSeries: [{ timeDefines: ["2026-09-09T11:00:00+09:00"],
    areas: [{ area: { name: "嶺北", code: "180010" }, weatherCodes: ["201"], weathers: ["くもり 時々 晴れ"], winds: ["南の風"] },
            { area: { name: "嶺南", code: "180020" }, weatherCodes: ["101"], weathers: ["晴れ 時々 くもり"], winds: ["南西の風"] }] }] }];

let counts = "day,count\n";
for (let i = 29; i >= 0; i--) counts += `2026080${i % 9 + 1},${40 + (i * 7) % 90}\n`;
counts += "20260908,118\n20260909,143\n";

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [], seen = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/ERR_|Failed to load/.test(m.text())) errors.push(m.text()); });

  const json = (o) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(o) });
  await page.route('**/*', async route => {
    const u = route.request().url();
    if (u.includes('code4fukui.github.io') && u.endsWith('all-cnt.csv')) {
      seen.push('all-cnt.csv');
      return route.fulfill({ status: 200, contentType: 'text/csv', body: counts });
    }
    if (u.includes('/forecast/data/forecast/180000.json')) { seen.push('jma forecast'); return route.fulfill(json(FORECAST)); }
    if (u.includes('/amedas/data/latest_time.txt')) {
      seen.push('latest_time'); return route.fulfill({ status: 200, contentType: 'text/plain', body: '2026-09-09T11:20:00+09:00' });
    }
    if (u.includes('/amedas/const/amedastable.json')) { seen.push('amedastable'); return route.fulfill(json(AMEDAS_TABLE)); }
    if (u.includes('/amedas/data/map/')) {
      seen.push('amedas map: ' + u.split('/map/')[1]); return route.fulfill(json(AMEDAS_OBS));
    }
    if (u.startsWith('file://')) return route.continue();
    return route.abort();   // tiles, OSRM: irrelevant here
  });

  await page.goto('file://' + path.join(__dirname, 'index.html'));
  await page.waitForTimeout(6000);

  const out = await page.evaluate(() => {
    const t = id => (document.getElementById(id) || {}).textContent || null;
    return {
      jmaNote: t('jma-live-note'),
      liveSurveyNote: t('live-survey-note'),
      jmaRows: [...document.querySelectorAll('#jma-rows .mini-row')]
        .map(r => r.querySelector('.name').textContent.trim() + ' = ' + r.querySelector('.val').textContent.trim()),
      resolved: window.__probe ? null : undefined,
    };
  });

  console.log('endpoints hit:'); [...new Set(seen)].forEach(s => console.log('  * ' + s));
  console.log('\nJMA note      :', out.jmaNote);
  console.log('Live survey   :', out.liveSurveyNote);
  console.log('\nJMA rows (station name = live observation):');
  out.jmaRows.forEach(r => console.log('  ' + r));

  await page.screenshot({ path: 'verify_live.png' });
  console.log('\nerrors:', errors.length);
  errors.slice(0, 10).forEach(e => console.log('  ! ' + e.slice(0, 200)));
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();
