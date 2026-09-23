/* ============================================================
   unlock.js — the reader half of scripts/crypto_data.py

   The dashboard's data is sealed: docs/metrics.json.enc and its three siblings
   are AES-256-GCM ciphertext under a key derived from the dashboard password.
   This file opens them, and is shared by index.html and data.html rather than
   copied into each, so the two cannot disagree about the format.

   WebCrypto only — no library. The envelope was chosen to be exactly what the
   browser already does: PBKDF2-HMAC-SHA256 to the key, AES-GCM with the tag on
   the end of the ciphertext (what Python's AESGCM returns), gzip inside
   (DecompressionStream). Each file is bound to its repo-relative path, so a file
   served under another name fails to open. crypto_data.py documents the
   envelope; change the two together or neither.

   MODES, and the page is told which it is in rather than guessing:

     encrypted  docs/*.json.enc is present. The gate derives a key and opens them.
     plain      no .enc, only docs/*.json — a checkout that has not been sealed.
                On localhost it loads, under a red banner. ANYWHERE ELSE it shows
                nothing: an unsealed build on a public host fails closed, because
                the page must never be the thing that displays unsealed data.
     missing    neither.

   The key held for the browser session is the derived key, never the password.
   One salt per password (not per run), so a key derived this morning still opens
   tonight's re-seal and a tab stays unlocked across the daily cron.

   crypto.subtle exists only in a secure context: HTTPS or localhost. Opened
   straight off the disk with file:// there is no crypto at all — serve docs/
   with `python3 -m http.server` to look at it locally.
   ============================================================ */
(function (global) {
  "use strict";

  var ENC = ".enc";
  var AAD_PREFIX = "align-dashboard/v1/";
  var DIR = "docs/";                  // the page's files are bound as docs/<name>
  var SESSION_KEY = "align-key";      // {salt, iter, bits} — the derived key, never the password

  var state = { mode: null, key: null, salt: null, iter: null, cache: {}, envelopes: {} };

  function b64ToBytes(b64) {
    var bin = atob(b64), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function bytesToB64(bytes) {
    var bin = "", a = new Uint8Array(bytes);
    for (var i = 0; i < a.length; i++) bin += String.fromCharCode(a[i]);
    return btoa(bin);
  }

  function subtle() {
    if (!global.crypto || !global.crypto.subtle) {
      throw new Error("This page needs to be served over HTTPS or from localhost — "
        + "the browser only provides crypto.subtle in a secure context.");
    }
    return global.crypto.subtle;
  }

  function isLocal() {
    var h = (global.location && global.location.hostname) || "";
    // 0.0.0.0 is what `python3 -m http.server` prints, and only this machine
    // can reach it.
    return h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0" || h === "::1"
      || h === "[::1]" || /\.localhost$/.test(h);
  }

  // Callers asking for data before the gate is passed PARK here rather than fail.
  // index.html renders several sections from top-level calls that run at
  // script-parse time, long before a password is typed; parking lets those keep
  // their shape. A page that is never unlocked just leaves them pending — which is
  // right, because it is showing the gate.
  var keyWaiters = [];
  function whenKeyed() {
    if (state.key) return Promise.resolve();
    return new Promise(function (resolve) { keyWaiters.push(resolve); });
  }
  function keyEstablished() {
    var w = keyWaiters; keyWaiters = [];
    w.forEach(function (resolve) { resolve(); });
  }

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (r.status === 404) return null;
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
      return r.json();
    });
  }

  // Memoised: the gate opens metrics.json.enc to test the password and the
  // dashboard then wants the same file; one download is enough.
  // A network failure is NOT remembered: a phone on a weak signal that lost one
  // request would otherwise report "not published" for the life of the page.
  function envelope(name) {
    if (!(name in state.envelopes)) {
      var p = fetchJson(name + ENC);
      state.envelopes[name] = p;
      p.catch(function () { if (state.envelopes[name] === p) delete state.envelopes[name]; });
    }
    return state.envelopes[name];
  }

  // Shape before anything else, so an unresolved merge conflict ({"conflict": ...})
  // or a truncated file is named as what it is -- not as a wrong password, a
  // changed key, or a raw atob error.
  function wellFormed(env) {
    return !!env && env.v === 1 && env.alg === "AES-256-GCM" && env.kdf === "PBKDF2-HMAC-SHA256"
      && typeof env.salt === "string" && typeof env.iv === "string" && typeof env.ct === "string"
      && typeof env.iter === "number" && (!env.zip || env.zip === "gzip");
  }
  function malformed(name) {
    return new Error(name + ".enc is not a readable sealed file — an unresolved merge "
      + "conflict or a broken publish. Nothing is wrong with your password.");
  }

  // Must stay identical to crypto_data.derive_key: PBKDF2-HMAC-SHA256 over the
  // UTF-8 password with the envelope's own salt and iteration count, 256 bits.
  function deriveBits(password, saltB64, iterations) {
    return subtle().importKey("raw", new TextEncoder().encode(password), "PBKDF2", false,
      ["deriveBits"]).then(function (material) {
        return subtle().deriveBits({ name: "PBKDF2", salt: b64ToBytes(saltB64),
          iterations: iterations, hash: "SHA-256" }, material, 256);
      });
  }

  // Non-extractable: nothing needs to read the key back out, so nothing can.
  function importKey(bits) {
    return subtle().importKey("raw", bits, { name: "AES-GCM" }, false, ["decrypt"]);
  }

  function gunzip(bytes) {
    if (typeof DecompressionStream === "undefined") {
      return Promise.reject(new Error("This browser cannot decompress the data "
        + "(no DecompressionStream) — use a current Chrome, Edge, Firefox or Safari."));
    }
    var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).arrayBuffer();
  }

  function openEnvelope(env, key, name) {
    if (!env || env.v !== 1 || env.alg !== "AES-256-GCM" || env.kdf !== "PBKDF2-HMAC-SHA256"
        || (env.zip && env.zip !== "gzip")) {
      return Promise.reject(new Error(name + ": unrecognised envelope format"));
    }
    var aad = new TextEncoder().encode(AAD_PREFIX + DIR + name);
    return subtle().decrypt({ name: "AES-GCM", iv: b64ToBytes(env.iv), additionalData: aad,
      tagLength: 128 }, key, b64ToBytes(env.ct))
      .then(function (body) { return env.zip === "gzip" ? gunzip(body) : body; })
      .then(function (plain) { return JSON.parse(new TextDecoder().decode(plain)); });
  }

  function storeKey(env, bits) {
    try {
      sessionStorage.setItem(SESSION_KEY,
        JSON.stringify({ salt: env.salt, iter: env.iter, bits: bytesToB64(bits) }));
    } catch (e) { /* private mode: the key lives for this page only */ }
  }
  function readStoredKey() {
    try { var raw = sessionStorage.getItem(SESSION_KEY); return raw ? JSON.parse(raw) : null; }
    catch (e) { return null; }
  }
  function clearKey() {
    try { sessionStorage.removeItem(SESSION_KEY); sessionStorage.removeItem("align-unlocked"); }
    catch (e) {}
  }

  function adopt(env, key, doc) {
    state.key = key; state.salt = env.salt; state.iter = env.iter;
    state.cache["metrics.json"] = Promise.resolve(doc);
    keyEstablished();
  }

  /* ---------- public ---------- */

  // ?sealed on a local URL tests the real gate against the sealed files even
  // when working copies sit beside them.
  function forceSealed() {
    return /(^|[?&])sealed(=|&|$)/.test((global.location && global.location.search || "").slice(1));
  }

  function detect() {
    if (state.mode) return Promise.resolve(state.mode);
    // On this machine a decrypted working copy is what you are working on, so it
    // wins over the sealed file beside it -- otherwise a rebuilt metrics.json is
    // "verified" against the last sealed numbers with nothing saying so.
    var local = isLocal() && !forceSealed()
      ? fetchJson("metrics.json").then(function (doc) { return doc; }, function () { return null; })
      : Promise.resolve(null);
    return local.then(function (working) {
      if (working) { state.working = true; return (state.mode = "plain"); }
      return envelope("metrics.json").then(function (env) {
        if (env) return (state.mode = "encrypted");
        return fetchJson("metrics.json").then(function (doc) {
          return (state.mode = doc ? "plain" : "missing");
        });
      });
    });
    // A rejection (network) leaves state.mode unset, so the next call probes again.
  }

  // Resolves true when the password opens the sealed metrics file (and keeps the
  // key for this tab), false when it does not. Anything else — no secure context,
  // no network — is thrown, so the gate can say what actually happened instead of
  // blaming the typist.
  function tryPassword(password) {
    // Fetched afresh on every attempt: a gate left open across a re-seal or a
    // password change would otherwise test the password against yesterday's
    // envelope -- rejecting the new password, or unlocking a stale file.
    delete state.envelopes["metrics.json"];
    return envelope("metrics.json").then(function (env) {
      if (!env) throw new Error("metrics.json.enc is not published — nothing to unlock.");
      if (!wellFormed(env)) throw malformed("metrics.json");
      // Derived once, used twice: imported for this page, and the same bits kept
      // for data.html. Deriving again would pay the deliberate cost twice.
      return deriveBits(password, env.salt, env.iter).then(function (bits) {
        return importKey(bits).then(function (key) {
          return openEnvelope(env, key, "metrics.json").then(function (doc) {
            storeKey(env, bits);
            adopt(env, key, doc);
            return true;
          });
        });
      }).catch(function (e) {
        // A wrong key fails the GCM tag as OperationError — the one failure that
        // means "wrong password". Everything else is rethrown.
        if (e && e.name === "OperationError") return false;
        throw e;
      });
    });
  }

  // Re-use this tab's key. False when there is none, or when the data has been
  // re-sealed under a new password since (a rotation mints a new salt).
  function resume() {
    var stored = readStoredKey();
    if (!stored) return Promise.resolve(false);
    return envelope("metrics.json").then(function (env) {
      if (!wellFormed(env) || env.salt !== stored.salt || env.iter !== stored.iter) {
        clearKey(); return false;
      }
      return importKey(b64ToBytes(stored.bits)).then(function (key) {
        return openEnvelope(env, key, "metrics.json").then(function (doc) {
          adopt(env, key, doc);
          return true;
        });
      }).catch(function () { clearKey(); return false; });
    });
  }

  // The one call the pages make for data. Takes the PLAINTEXT name and returns
  // parsed JSON. Memoised per name, so every card that wants metrics.json shares
  // one fetch and one decrypt.
  function load(name) {
    if (name in state.cache) return state.cache[name];
    var p = detect().then(function (mode) {
      if (mode === "missing") throw new Error(name + " is not published");
      if (mode === "plain") {
        if (!isLocal()) {
          throw new Error("This deployment has not been sealed yet, so it shows nothing "
            + "(unsealed data opens only on localhost). The data is encrypted by the Seal "
            + "dashboard data workflow once the DASHBOARD_PASSWORD secret is set.");
        }
        return fetchJson(name).then(function (doc) {
          if (!doc) throw new Error(name + " is missing");
          return doc;
        });
      }
      return whenKeyed().then(function () { return envelope(name); }).then(function (env) {
        if (!env) throw new Error(name + ENC + " is missing");
        if (!wellFormed(env)) throw malformed(name);
        if (env.salt !== state.salt || env.iter !== state.iter) {
          throw new Error(name + " is sealed under a different key than the one this tab "
            + "unlocked — the password was changed. Reload and enter the new one.");
        }
        return openEnvelope(env, state.key, name);
      });
    });
    state.cache[name] = p;
    // A failure is not remembered: a later call gets a real attempt.
    p.catch(function () { if (state.cache[name] === p) delete state.cache[name]; });
    return p;
  }

  // Local, unsealed only. It has to be obvious on sight, because the only thing
  // separating it from the real site is which files are in docs/.
  function plainBanner() {
    if (document.getElementById("align-plain-banner")) return;
    var bar = document.createElement("div");
    bar.id = "align-plain-banner";
    bar.textContent = state.working
      ? "LOCAL WORKING COPY — showing your plaintext docs/*.json, not the sealed files. "
        + "Add ?sealed to the URL to test the real gate."
      : "UNSEALED DATA — this local build is serving plaintext docs/*.json with no password "
        + "protection. Public hosts refuse to show it.";
    bar.setAttribute("style", ["position:sticky", "top:0", "z-index:9999",
      "background:#b3261e", "color:#fff", "font:600 12px/1.5 ui-sans-serif,system-ui,sans-serif",
      "letter-spacing:.4px", "padding:8px 14px", "text-align:center"].join(";"));
    document.body.insertBefore(bar, document.body.firstChild);
  }

  global.AlignUnlock = {
    detect: detect, tryPassword: tryPassword, resume: resume, load: load,
    clearKey: clearKey, isLocal: isLocal, plainBanner: plainBanner,
    isUnlocked: function () { return !!state.key; },
  };
})(window);
