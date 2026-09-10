const { chromium } = require('playwright');
const path = require('path');

// The container cannot reach code4fukui.github.io or jma.go.jp (egress policy), so
// this run also doubles as the offline-fallback test: every live fetch WILL fail and
// the page must still render correctly from baked data with no uncaught errors.
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

  const errors = [], warnings = [], failedReq = [];
  page.on('console', m => {
    if (m.type() === 'error') errors.push(m.text());
    if (m.type() === 'warning') warnings.push(m.text());
  });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('requestfailed', r => failedReq.push(r.url().slice(0, 70)));

  await page.goto('file://' + path.join(__dirname, 'index.html'));
  await page.waitForTimeout(4000);

  const snap = await page.evaluate(() => {
    const t = id => (document.getElementById(id) || {}).textContent || null;
    const rows = [...document.querySelectorAll('#congestion-rows .mini-row')]
      .map(r => r.querySelector('.name').textContent.trim() + ' = ' + r.querySelector('.val').textContent.trim());
    const cams = [...document.querySelectorAll('#camera-rows .mini-row')]
      .map(r => r.querySelector('.val').textContent.trim());
    const econ = [...document.querySelectorAll('#econ-breakdown .econ-row')]
      .map(r => r.querySelector('.econ-row-name').textContent.trim() + ' ' + r.querySelector('.econ-row-val').textContent.trim());
    const jma = [...document.querySelectorAll('#jma-rows .mini-row')]
      .map(r => r.querySelector('.name').textContent.trim() + ' = ' + r.querySelector('.val').textContent.trim());
    return {
      title: document.title,
      banner: t('top-banner-text'),
      rsi: t('rsi-big'), sentiment: t('sentiment-val'), sentLabel: t('sentiment-label'),
      camera: t('camera-big'), hotel: t('hotel-big'),
      winterDrop: t('stat-winter-drop'), ishikawa: t('stat-ishikawa'),
      jmaNote: t('jma-live-note'), liveNote: t('live-survey-note'),
      congestion: rows, cameras: cams, econ: econ.slice(0, 4), jma: jma.slice(0, 4),
      nodeTableRows: document.querySelectorAll('#node-table-body tr').length,
      dotsOnMap: document.querySelectorAll('#map svg path').length,
      dataMeta: window.DHDE_DATA ? 'exposed' : 'scoped (good)',
    };
  });

  console.log(JSON.stringify(snap, null, 1));

  // Scrub the timeline to winter and re-read, to prove interpolation works on real data.
  await page.evaluate(() => {
    const s = document.getElementById('timeline-slider');
    s.value = 300; s.dispatchEvent(new Event('input'));
  });
  await page.waitForTimeout(1200);
  const winter = await page.evaluate(() => ({
    caption: (document.getElementById('timeline-caption') || {}).textContent,
    congestion: [...document.querySelectorAll('#congestion-rows .mini-row')]
      .map(r => r.querySelector('.name').textContent.trim() + ' = ' + r.querySelector('.val').textContent.trim()),
    camera: (document.getElementById('camera-big') || {}).textContent,
    hotel: (document.getElementById('hotel-big') || {}).textContent,
  }));
  console.log('\n--- scrubbed to winter ---');
  console.log(JSON.stringify(winter, null, 1));

  // Click through every view tab looking for tab-specific crashes.
  const tabs = await page.$$('.view-tab');
  for (const tab of tabs) { await tab.click(); await page.waitForTimeout(350); }
  // Fire a scenario.
  const sc = await page.$('.scenario-btn');
  if (sc) { await sc.click(); await page.waitForTimeout(600); }
  // Flip to Japanese.
  await page.click('#lang-toggle'); await page.waitForTimeout(800);
  const ja = await page.evaluate(() => (document.getElementById('top-banner-text') || {}).textContent);
  console.log('\nJA banner:', ja);

  await page.screenshot({ path: 'verify.png', fullPage: false });

  console.log('\n=== console errors: ' + errors.length + ' ===');
  errors.slice(0, 15).forEach(e => console.log('  ! ' + e.slice(0, 160)));
  console.log('=== failed requests (expected: blocked live sources) ===');
  [...new Set(failedReq)].slice(0, 8).forEach(u => console.log('  - ' + u));

  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();
