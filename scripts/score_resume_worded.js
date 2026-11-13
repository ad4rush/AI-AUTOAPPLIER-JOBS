(async () => {
  const resumePath = process.argv[2] || './master_resumes/RESUME_1_AI_ENGINEER.pdf';

  const task = await taskSpace('rw_live_score_' + Date.now(), { profileId: 'Profile 1' });
  const page = task.page('p1');

  console.log('[*] Navigating to https://resumeworded.com/score.php ...');
  await page.goto('https://resumeworded.com/score.php', { waitUntil: 'domcontentloaded', timeout: 35000 });
  await new Promise(r => setTimeout(r, 4000));

  console.log('[*] Page URL:', await page.url());
  console.log('[*] Page Title:', await page.title());

  // Attach file
  console.log('[*] Attaching file:', resumePath);
  try {
    await page.setInputFiles('input[type="file"], input.dz-hidden-input', [resumePath]);
    console.log('[✓] setInputFiles succeeded!');
  } catch (err) {
    console.log('[!] setInputFiles error:', err.message);
    console.log('[*] Trying click on upload dropzone with waitForFileChooser...');
    const chooserPromise = page.waitForFileChooser({ timeout: 10000 });
    await page.click('.dropzone, [class*="upload"]');
    const chooser = await chooserPromise;
    await chooser.setFiles(resumePath);
    console.log('[✓] FileChooser succeeded!');
  }

  console.log('[*] File attached. Waiting for analysis / results page...');

  // Poll for up to 60 seconds for results
  let finalUrl = '';
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 3000));
    finalUrl = await page.url();
    const t = await page.title();
    console.log(`[Elapsed ${(i + 1) * 3}s] Title: ${t} | URL: ${finalUrl}`);

    // If career level modal appeared, click Entry Level
    try {
      const clicked = await page.evaluate(() => {
        const entryBtn = document.querySelector('[data-level="entrylevel"], button:contains("Entry"), div[class*="level"]');
        if (entryBtn) {
          entryBtn.click();
          return true;
        }
        return false;
      });
      if (clicked) console.log('[*] Clicked entrylevel card!');
    } catch (e) {}

    if (finalUrl.includes('results') || finalUrl.includes('score') || finalUrl.includes('signup-page')) {
      // Check if score is visible on page
      const hasScore = await page.evaluate(() => {
        const text = document.body.innerText;
        return text.includes('Your resume scored') || text.includes('/100') || text.includes('OVERALL');
      });
      if (hasScore) {
        console.log('[✓] Detected score text on page!');
        break;
      }
    }
  }

  // Extract score data
  const scoreReport = await page.evaluate(() => {
    const text = document.body.innerText;
    const overallMatch = text.match(/Your resume scored\s+(\d+)\s+out of 100/i) || text.match(/(\d+)\s+OVERALL/i) || text.match(/score:\s*(\d+)/i);
    const brevityMatch = text.match(/Brevity\s*(\d+)\/100/i) || text.match(/Brevity[^\d]+(\d+)/i);
    const impactMatch = text.match(/Impact\s*(\d+)\/100/i) || text.match(/Impact[^\d]+(\d+)/i);
    const styleMatch = text.match(/Style\s*(\d+)\/100/i) || text.match(/Style[^\d]+(\d+)/i);
    const sectionsMatch = text.match(/Sections\s*(\d+)\/100/i) || text.match(/Sections[^\d]+(\d+)/i);

    const scoresFound = [];
    document.querySelectorAll('[class*="score"], .overview-single-score, .card, h1, h2, h3, .score-circle').forEach(el => {
      const t = el.innerText.replace(/\s+/g, ' ').trim();
      if ((t.includes('/100') || t.includes('/10') || t.includes('OVERALL') || t.includes('Score')) && t.length < 60) {
        scoresFound.push(t);
      }
    });

    return {
      title: document.title,
      url: window.location.href,
      overallScore: overallMatch ? overallMatch[1] : null,
      subscores: {
        brevity: brevityMatch ? brevityMatch[1] : null,
        impact: impactMatch ? impactMatch[1] : null,
        style: styleMatch ? styleMatch[1] : null,
        sections: sectionsMatch ? sectionsMatch[1] : null
      },
      scoresFound: Array.from(new Set(scoresFound)),
      bodySnippet: text.slice(0, 1500)
    };
  });

  console.log('[*] Resume Worded Score Report:');
  console.log(JSON.stringify(scoreReport, null, 2));

  const fs = require('fs');
  fs.writeFileSync('./data/resume_worded_live_report.json', JSON.stringify(scoreReport, null, 2), 'utf8');
})();
