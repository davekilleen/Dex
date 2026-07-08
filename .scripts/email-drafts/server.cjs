#!/usr/bin/env node
'use strict';

// Local dashboard server for the email drafts queue.
// Plain Node http (no deps) so this stays a zero-install double-click tool.
// Serves the static dashboard from public/ and a small REST API over data/drafts.json.

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { execFile, execFileSync } = require('child_process');
const https = require('https');

const ROOT = __dirname;
const PUBLIC_DIR = path.join(ROOT, 'public');
// Overridable so tests can run against a throwaway queue on a free port.
const DATA_DIR = process.env.EMAIL_DRAFTS_DATA_DIR || path.join(ROOT, 'data');
const DRAFTS_FILE = path.join(DATA_DIR, 'drafts.json');
const PUSH_SCRIPT = path.join(ROOT, 'push-to-outlook.ps1');
const PORT = Number(process.env.EMAIL_DRAFTS_PORT) || 4747;

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function loadDrafts() {
  if (!fs.existsSync(DRAFTS_FILE)) return [];
  const raw = fs.readFileSync(DRAFTS_FILE, 'utf8').trim();
  if (!raw) return [];
  return JSON.parse(raw);
}

function saveDrafts(drafts) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(DRAFTS_FILE, JSON.stringify(drafts, null, 2), 'utf8');
}

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > 5 * 1024 * 1024) {
        reject(new Error('Request body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(new Error('Invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

// Spawns push-to-outlook.ps1 via `-Command` (not `-File` -- that form loses
// access to Outlook COM, see outreach-drafts-custom/SKILL.md).
function pushToOutlook(items) {
  return new Promise((resolve, reject) => {
    const tempFile = path.join(os.tmpdir(), `dex-email-push-${crypto.randomBytes(6).toString('hex')}.json`);
    fs.writeFileSync(tempFile, JSON.stringify(items), 'utf8');

    const escape = (s) => s.replace(/'/g, "''");
    const psCommand = `& '${escape(PUSH_SCRIPT)}' -DraftsFile '${escape(tempFile)}'`;

    execFile(
      'powershell.exe',
      ['-NoProfile', '-Command', psCommand],
      { timeout: 60000, maxBuffer: 10 * 1024 * 1024 },
      (err, stdout, stderr) => {
        fs.unlink(tempFile, () => {});
        if (err && !stdout) {
          return reject(new Error(stderr || err.message));
        }
        try {
          const parsed = JSON.parse(stdout);
          resolve(Array.isArray(parsed) ? parsed : [parsed]);
        } catch (e) {
          reject(new Error(`Failed to parse PowerShell output: ${stdout || stderr}`));
        }
      }
    );
  });
}

function serveStatic(req, res, pathname) {
  let reqPath = pathname === '/' ? '/index.html' : pathname;
  reqPath = path.normalize(reqPath).replace(/^(\.\.[/\\])+/, '');
  const fullPath = path.join(PUBLIC_DIR, reqPath);
  if (!fullPath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }
  fs.readFile(fullPath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    const ext = path.extname(fullPath);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  const parsedUrl = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = parsedUrl.pathname;

  try {
    if (req.method === 'GET' && pathname === '/api/drafts') {
      return sendJson(res, 200, loadDrafts());
    }

    let m = pathname.match(/^\/api\/drafts\/([^/]+)$/);
    if (req.method === 'PUT' && m) {
      const id = decodeURIComponent(m[1]);
      const body = await readJsonBody(req);
      const drafts = loadDrafts();
      const idx = drafts.findIndex((d) => d.id === id);
      if (idx === -1) return sendJson(res, 404, { error: 'Draft not found' });

      const editable = ['to', 'cc', 'subject', 'body', 'sendMode'];
      for (const key of editable) {
        if (Object.prototype.hasOwnProperty.call(body, key)) drafts[idx][key] = body[key];
      }
      if (drafts[idx].status === 'needs_email' && drafts[idx].to) {
        drafts[idx].status = 'queued';
      }
      saveDrafts(drafts);
      return sendJson(res, 200, drafts[idx]);
    }

    if (req.method === 'DELETE' && m) {
      const id = decodeURIComponent(m[1]);
      const drafts = loadDrafts();
      const next = drafts.filter((d) => d.id !== id);
      if (next.length === drafts.length) return sendJson(res, 404, { error: 'Draft not found' });
      saveDrafts(next);
      return sendJson(res, 200, { ok: true });
    }

    m = pathname.match(/^\/api\/drafts\/([^/]+)\/push$/);
    if (req.method === 'POST' && m) {
      const id = decodeURIComponent(m[1]);
      const drafts = loadDrafts();
      const idx = drafts.findIndex((d) => d.id === id);
      if (idx === -1) return sendJson(res, 404, { error: 'Draft not found' });

      const draft = drafts[idx];
      if (!draft.to) return sendJson(res, 400, { error: 'No recipient email set' });

      let results;
      try {
        results = await pushToOutlook([
          { id: draft.id, to: draft.to, cc: draft.cc || '', subject: draft.subject, body: draft.body, sendMode: draft.sendMode || 'draft' },
        ]);
      } catch (e) {
        draft.status = 'failed';
        draft.error = e.message;
        saveDrafts(drafts);
        return sendJson(res, 502, { error: e.message, draft });
      }

      const result = results.find((r) => r.id === draft.id) || results[0];
      draft.status = result.status;
      draft.error = result.error || null;
      saveDrafts(drafts);
      return sendJson(res, 200, draft);
    }

    // ── Salesforce contact lookup ──────────────────────────────────────────
    if (req.method === 'GET' && pathname === '/api/sf-lookup') {
      const contactName = parsedUrl.searchParams.get('contact') || '';
      const company     = parsedUrl.searchParams.get('company') || '';
      if (!contactName.trim()) return sendJson(res, 400, { error: 'contact param required' });
      try {
        const nameEsc    = contactName.replace(/'/g, "''");
        const companyEsc = company.replace(/'/g, "''");
        const psScript = [
          "$ErrorActionPreference = 'Stop'",
          "$tokensFile = Join-Path $env:USERPROFILE '.claude' 'sf_tokens.json'",
          "if (-not (Test-Path $tokensFile)) { throw 'sf_tokens.json not found' }",
          "$tokens = Get-Content $tokensFile | ConvertFrom-Json",
          "$inst = $tokens.instance_url",
          "$tok  = $tokens.access_token",
          "$hdr  = @{ Authorization = \"Bearer $tok\" }",
          `$q1 = [Uri]::EscapeDataString("SELECT Id,FirstName,LastName,Title,Email,Phone,Account.Name FROM Contact WHERE Name LIKE '%${nameEsc}%' LIMIT 5")`,
          "$r1 = Invoke-RestMethod -Uri \"$inst/services/data/v58.0/query?q=$q1\" -Headers $hdr",
          "$contacts = $r1.records",
          "if ($contacts.Count -eq 0) {",
          `  $q2 = [Uri]::EscapeDataString("SELECT Id,FirstName,LastName,Title,Email,Phone,Account.Name FROM Contact WHERE Account.Name LIKE '%${companyEsc}%' LIMIT 5")`,
          "  $r2 = Invoke-RestMethod -Uri \"$inst/services/data/v58.0/query?q=$q2\" -Headers $hdr",
          "  $contacts = $r2.records",
          "}",
          "if ($contacts.Count -eq 0) { Write-Output '{\"found\":false}'; exit }",
          "$c = $contacts[0]",
          "$obj = @{ found=$true; id=$c.Id; name=\"$($c.FirstName) $($c.LastName)\".Trim(); title=$c.Title; email=$c.Email; phone=$c.Phone; account=if($c.Account){$c.Account.Name}else{''} }",
          "Write-Output ($obj | ConvertTo-Json -Compress)",
        ].join('\n');
        const raw = execFileSync('powershell.exe', ['-NoProfile', '-Command', psScript], {
          timeout: 20000, maxBuffer: 2 * 1024 * 1024, encoding: 'utf8',
        });
        return sendJson(res, 200, JSON.parse(raw.trim()));
      } catch (e) {
        return sendJson(res, 200, { found: false, error: 'SF lookup failed: ' + e.message.split('\n')[0] });
      }
    }

    // ── AI Rewrite ────────────────────────────────────────────────────────────
    if (req.method === 'POST' && pathname === '/api/rewrite') {
      const body = await readJsonBody(req);
      const { contactName, company, subject, body: emailBody, instruction } = body;
      if (!instruction) return sendJson(res, 400, { error: 'instruction required' });

      let apiKey = '';
      try {
        const envPath = path.join(ROOT, '..', '..', '.env');
        if (fs.existsSync(envPath)) {
          const envText = fs.readFileSync(envPath, 'utf8');
          const m = envText.match(/^ANTHROPIC_API_KEY\s*=\s*(.+)$/m);
          if (m) apiKey = m[1].trim().replace(/^["']|["']$/g, '');
        }
      } catch (_) {}
      if (!apiKey) return sendJson(res, 500, { error: 'ANTHROPIC_API_KEY not found in .env' });

      const prompt = `You are helping Chris Barsanti at Mid Atlantic Machinery rewrite a sales/service follow-up email.\n\nContact: ${contactName || 'unknown'}\nCompany: ${company || 'unknown'}\nCurrent subject: ${subject || ''}\n\nCurrent email body:\n${emailBody || ''}\n\nRewrite instruction: ${instruction}\n\nRules:\n- ASCII only, no em dashes, no smart quotes\n- Sign off as: Chris Barsanti\\nMid Atlantic Machinery\n- Professional but conversational\n- Return ONLY a raw JSON object (no markdown fences) with keys "subject" (string) and "body" (string).`;

      try {
        const claudeRes = await new Promise((resolve, reject) => {
          const payload = JSON.stringify({ model: 'claude-haiku-4-5', max_tokens: 1024, messages: [{ role: 'user', content: prompt }] });
          const options = {
            hostname: 'api.anthropic.com', path: '/v1/messages', method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
          };
          const req2 = https.request(options, (r2) => {
            const chunks = [];
            r2.on('data', (c) => chunks.push(c));
            r2.on('end', () => resolve({ status: r2.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
          });
          req2.on('error', reject);
          req2.write(payload);
          req2.end();
        });
        const claudeData = JSON.parse(claudeRes.body);
        if (claudeRes.status !== 200) return sendJson(res, 502, { error: claudeData.error?.message || 'Claude API error' });
        const text = claudeData.content[0].text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
        return sendJson(res, 200, JSON.parse(text));
      } catch (e) {
        return sendJson(res, 500, { error: 'Rewrite failed: ' + e.message });
      }
    }

    if (req.method === 'POST' && pathname === '/api/drafts/push-all') {
      const drafts = loadDrafts();
      const toPush = drafts.filter((d) => d.status === 'queued' && d.to);
      if (toPush.length === 0) return sendJson(res, 200, { pushed: 0, results: [] });

      let results;
      try {
        results = await pushToOutlook(
          toPush.map((d) => ({ id: d.id, to: d.to, cc: d.cc || '', subject: d.subject, body: d.body, sendMode: d.sendMode || 'draft' }))
        );
      } catch (e) {
        return sendJson(res, 502, { error: e.message });
      }

      const byId = new Map(results.map((r) => [r.id, r]));
      for (const draft of drafts) {
        const result = byId.get(draft.id);
        if (result) {
          draft.status = result.status;
          draft.error = result.error || null;
        }
      }
      saveDrafts(drafts);
      return sendJson(res, 200, { pushed: toPush.length, results });
    }

    if (req.method === 'GET') {
      return serveStatic(req, res, pathname);
    }

    sendJson(res, 404, { error: 'Not found' });
  } catch (e) {
    sendJson(res, 500, { error: e.message });
  }
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`Port ${PORT} is already in use -- the dashboard is probably already running at http://localhost:${PORT}`);
    process.exit(1);
  }
  throw err;
});

server.listen(PORT, () => {
  console.log(`Email drafts dashboard running at http://localhost:${PORT}`);
});
