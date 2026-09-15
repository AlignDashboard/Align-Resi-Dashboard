/* ============================================================
   unlock.js — the reader half of scripts/crypto_data.py

   The dashboard's data files are sealed: docs/metrics.json.enc and friends are
   AES-256-GCM ciphertext under a key derived from the dashboard password. This
   file is what opens them, and it is shared by index.html and data.html rather
   than copied into each — the two must not be able to disagree about a format,
   and a second copy would drift the first time one was edited.

   Everything here is WebCrypto. No library is fetched, because the format was
   chosen to be exactly what SubtleCrypto already does: PBKDF2-HMAC-SHA256 to
   the key, AES-GCM with the tag appended to the ciphertext, which is what
   Python's AESGCM.encrypt returns. scripts/crypto_data.py documents the
   envelope; change the two together or neither.

   THREE MODES, and the page is told which one it is in rather than guessing:

     encrypted  docs/*.json.enc is present. The password gate derives a key and
                opens them. This is what the live site is.
     plain      no .enc, but docs/*.json is there — a local checkout that has
                run the pipeline and not sealed it. Loads, and says so in a
                banner that cannot be missed, because an unsealed build looking
                identical to a sealed one is how an unsealed one gets deployed.
     missing    neither. An honest error beats an empty dashboard.

   NOTE ON SECURE CONTEXT: crypto.subtle exists only over HTTPS or on
   localhost. Opening the file off the disk with file:// gives no crypto.subtle
   at all, so `python3 -m http.server` in docs/ is the way to look at this
   locally. The page says as much rather than failing as "undefined".
   ============================================================ */
(function (global) {
  "use strict";

  var ENC = ".enc";
  var SESSION_KEY = "align-key";      // {salt, bits} — the derived key, not the password
  var LEGACY_MARKER = "align-unlocked";

  // Files the pages ask for by their PLAINTEXT name; the loader decides whether
  // that means fetching the sealed one and opening it.
  var state = {
    mode: null,                       // "encrypted" | "plain" | "missing"
    key: null,                        // CryptoKey, once a password has opened something
    salt: null,                       // base64, the salt that key was derived from
    cache: {},                        // name -> Promise of parsed JSON
    envelopes: {},                    // name -> Promise of envelope or null
  };

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

  // Callers that ask for data before the gate has been passed park here rather
  // than failing. index.html renders several sections from top-level calls that
  // run at script-parse time — long before anyone has typed a password — and
  // parking lets those keep their shape instead of every one of them growing
  // its own "wait for unlock" dance.
  var keyWaiters = [];
  function whenKeyed() {
    if (state.key) return Promise.resolve();
    return new Promise(function (resolve) { keyWaiters.push(resolve); });
  }
  function keyEstablished() {
    var waiting = keyWaiters;
    keyWaiters = [];
    waiting.forEach(function (resolve) { resolve(); });
  }

  function subtle() {
    if (!global.crypto || !global.crypto.subtle) {
      throw new Error("This page needs to be served over HTTPS or from localhost — "
        + "the browser only provides crypto.subtle in a secure context.");
    }
    return global.crypto.subtle;
  }

  /* ---------- fetching ---------- */

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (r.status === 404) return null;
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // Memoised: the gate opens metrics.json.enc to check the password and the
  // dashboard then wants the same file, and one 150KB download is enough.
  function envelope(name) {
    if (!(name in state.envelopes)) {
      state.envelopes[name] = fetchJson(name + ENC).catch(function () { return null; });
    }
    return state.envelopes[name];
  }

  /* ---------- key derivation ---------- */

  // Must stay identical to crypto_data.derive_key: PBKDF2-HMAC-SHA256 over the
  // UTF-8 password, the envelope's own salt and iteration count, 256 bits out.
  function deriveBits(password, saltB64, iterations) {
    var enc = new TextEncoder();
    return subtle().importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"])
      .then(function (material) {
        return subtle().deriveBits({
          name: "PBKDF2", salt: b64ToBytes(saltB64),
          iterations: iterations, hash: "SHA-256",
        }, material, 256);
      });
  }

  // Imported non-extractable: nothing needs to read the key back out, and a key
  // that cannot be exported cannot be exfiltrated by anything that gets a
  // reference to it.
  function importKey(bits) {
    return subtle().importKey("raw", bits, { name: "AES-GCM" }, false, ["decrypt"]);
  }

  function openEnvelope(env, key, name) {
    if (env.v !== 1 || env.alg !== "AES-256-GCM" || env.kdf !== "PBKDF2-HMAC-SHA256") {
      return Promise.reject(new Error(name + ": unrecognised envelope format"));
    }
    // The filename is authenticated, so serving one file's ciphertext under
    // another's name fails here rather than decrypting to the wrong thing.
    var aad = new TextEncoder().encode("align-dashboard/v1/" + name);
    return subtle().decrypt(
      { name: "AES-GCM", iv: b64ToBytes(env.iv), additionalData: aad, tagLength: 128 },
      key, b64ToBytes(env.ct)
    ).then(function (plain) {
      return JSON.parse(new TextDecoder().decode(plain));
    });
  }

  /* ---------- session key ---------- */

  function storeKey(saltB64, bits) {
    try {
      sessionStorage.setItem(SESSION_KEY,
        JSON.stringify({ salt: saltB64, bits: bytesToB64(bits) }));
      // data.html's older gate looked for this; harmless to keep writing, and it
      // keeps a stale tab from bouncing in a loop mid-deploy.
      sessionStorage.setItem(LEGACY_MARKER, "1");
    } catch (e) { /* private mode: the key just lives for this page */ }
  }
  function readStoredKey() {
    try {
      var raw = sessionStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function clearKey() {
    try {
      sessionStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(LEGACY_MARKER);
    } catch (e) {}
  }

  /* ---------- public API ---------- */

  // Which mode are we in? Decided once, from whether the sealed metrics file is
  // actually there, and cached — every later call is free.
  function detect() {
    if (state.mode) return Promise.resolve(state.mode);
    return envelope("metrics.json").then(function (env) {
      if (env) { state.mode = "encrypted"; return state.mode; }
      return fetchJson("metrics.json").then(function (doc) {
        state.mode = doc ? "plain" : "missing";
        return state.mode;
      }).catch(function () { state.mode = "missing"; return state.mode; });
    });
  }

  // Try a password against the sealed metrics file. Resolves true when it opens
  // and caches the key for this browser session, false when it does not.
  // Anything other than a wrong password (no network, no secure context) is
  // thrown, so the gate can say which it was.
  function tryPassword(password) {
    return envelope("metrics.json").then(function (env) {
      if (!env) throw new Error("metrics.json.enc is not published — nothing to unlock.");
      // Derived once and used twice: importKey for this page, and the same bits
      // stored for data.html. Deriving again to get them would pay the (very
      // deliberate) PBKDF2 cost a second time for no reason.
      return deriveBits(password, env.salt, env.iter).then(function (bits) {
        return importKey(bits).then(function (key) {
          return openEnvelope(env, key, "metrics.json").then(function (doc) {
            state.key = key;
            state.salt = env.salt;
            state.cache["metrics.json"] = Promise.resolve(doc);
            storeKey(env.salt, bits);
            keyEstablished();
            return true;
          });
        });
      }).catch(function (e) {
        // A wrong key fails the GCM tag check as OperationError, which is the
        // one failure that means "wrong password" rather than "broken". Anything
        // else — no secure context, no network — is rethrown so the gate can say
        // what actually happened instead of blaming the typist.
        if (e && e.name === "OperationError") return false;
        if (e instanceof SyntaxError) return false;
        throw e;
      });
    });
  }

  // Re-use a key from earlier in this browser session. False if there is none,
  // or if the data has been re-sealed since (the daily run picks a new salt),
  // in which case the caller shows the gate again.
  function resume() {
    var stored = readStoredKey();
    if (!stored) return Promise.resolve(false);
    return envelope("metrics.json").then(function (env) {
      if (!env || env.salt !== stored.salt) { clearKey(); return false; }
      return importKey(b64ToBytes(stored.bits)).then(function (key) {
        return openEnvelope(env, key, "metrics.json").then(function (doc) {
          state.key = key;
          state.salt = env.salt;
          state.cache["metrics.json"] = Promise.resolve(doc);
          keyEstablished();
          return true;
        });
      }).catch(function () { clearKey(); return false; });
    });
  }

  // The one call the pages make for data. Takes the PLAINTEXT name — "metrics.json"
  // — and returns parsed JSON whichever mode the page is in. Memoised per name,
  // so the two places that both want metrics.json share one fetch and one decrypt.
  function load(name) {
    if (name in state.cache) return state.cache[name];
    state.cache[name] = detect().then(function (mode) {
      if (mode === "plain") {
        return fetchJson(name).then(function (doc) {
          if (!doc) throw new Error(name + " is missing");
          return doc;
        });
      }
      if (mode === "missing") throw new Error(name + " is not published");
      // Parks until the gate produces a key. A page that is never unlocked
      // simply leaves these pending, which is correct: it is showing the gate.
      return whenKeyed().then(function () { return envelope(name); }).then(function (env) {
        if (!env) throw new Error(name + ENC + " is missing");
        if (env.salt !== state.salt) {
          // Sealed in a different run from the one the key came from. Rather
          // than fail, derive nothing and say so: the caller re-prompts.
          throw new Error(name + " was re-sealed after unlocking — reload the page");
        }
        return openEnvelope(env, state.key, name);
      });
    });
    // A failed load must not be remembered as a failure forever — a later call
    // after unlocking should get a real attempt.
    state.cache[name].catch(function () { delete state.cache[name]; });
    return state.cache[name];
  }

  // Shown only in "plain" mode. An unsealed build has to be obvious on sight,
  // because the only thing separating it from the real one is which files are
  // in docs/ — and it is the sealed one that is supposed to be deployed.
  function plainBanner() {
    if (document.getElementById("align-plain-banner")) return;
    var bar = document.createElement("div");
    bar.id = "align-plain-banner";
    bar.textContent = "UNSEALED DATA — this build is serving plaintext docs/*.json "
      + "with no password protection. Run scripts/crypto_data.py encrypt before deploying.";
    bar.setAttribute("style", [
      "position:sticky", "top:0", "z-index:9999", "background:#b3261e", "color:#fff",
      "font:600 12px/1.5 ui-sans-serif,system-ui,sans-serif", "letter-spacing:.4px",
      "padding:8px 14px", "text-align:center",
    ].join(";"));
    document.body.insertBefore(bar, document.body.firstChild);
  }

  global.AlignUnlock = {
    detect: detect,
    tryPassword: tryPassword,
    resume: resume,
    load: load,
    clearKey: clearKey,
    hasStoredKey: function () { return !!readStoredKey(); },
    plainBanner: plainBanner,
    isUnlocked: function () { return !!state.key; },
  };
})(window);
