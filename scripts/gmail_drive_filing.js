/**
 * Auto-file Gmail report attachments into sorted Google Drive subfolders.
 * Runs in Google Apps Script under dashboard@alignrealestate.com, on an hourly
 * trigger. Originally written by Oliver Heldfond; this copy is the version of
 * record.
 *
 * WHY THIS LIVES IN THE REPO
 *   ROUTING_RULES below and config/report_map.json are two halves of one
 *   contract: this script decides which folder a report lands in, and
 *   report_map.json decides which folder the pipeline reads. A folder name that
 *   appears in only one of them is a report that arrives and is never parsed --
 *   silently, because both sides "work". scripts/test_routing.py asserts the two
 *   agree; run it after editing either file.
 *
 * DEPLOYING A CHANGE
 *   1. Edit here, run `python scripts/test_routing.py`, commit.
 *   2. script.google.com -> the "file downloader" project -> paste this in.
 *   3. Re-enter CONFIG.TARGET_FOLDER_ID if a full paste blanked it (see SOP s6).
 *   4. Run previewRouting (dry run, changes nothing) and read the log.
 *   5. If it looks right, run resortExistingFiles to rescue _Unsorted.
 *   Do NOT re-run createHourlyTrigger -- the existing trigger survives edits,
 *   and running it again just makes a duplicate.
 *
 * FUNCTIONS YOU CAN RUN
 *   previewRouting        - DRY RUN: logs where existing files would go.
 *   checkFolders          - DRY RUN: every rule's folder vs what Drive really has.
 *   fileGmailPdfsToDrive  - the main job (what the hourly trigger calls)
 *   createHourlyTrigger   - run ONCE, ever, to schedule the job
 *   resortExistingFiles   - move loose/_Unsorted files into their subfolders
 */

// =========================== CONFIG =============================
const CONFIG = {
  // File types to save. NOTE: 'csv' is deliberately absent. The EliseAI
  // building-metrics CSVs already reach Drive by another route, un-prefixed;
  // filing them from email too would create a second, date-prefixed copy in the
  // same folder, and populate_building_metrics.py picks the newest by sorted
  // filename -- "2026-08-31 metrics-building..." sorts before
  // "metrics-building...", so the wrong file would win. Leave csv out unless
  // that picker is changed first.
  ALLOWED_EXTENSIONS: ['pdf', 'xlsx', 'xls', 'docx', 'doc'],

  // Which emails to look at. 'has:attachment' checks every email.
  SEARCH_QUERY: 'has:attachment',

  // The MAIN Drive folder ("Report Lander"). Subfolders are created inside it.
  // This is the same folder the pipeline scans via the GDRIVE_FOLDER_ID secret;
  // if one changes, both change.
  TARGET_FOLDER_ID: '1RJK4HRcwHzHRW69-kaNxbNd9vNYkwT5T',

  // Gmail label applied once a thread is filed, so it's never processed twice.
  PROCESSED_LABEL: 'filed-to-drive',

  // Prefix saved files with the email date, e.g. "2026-07-14 RentRoll.xlsx".
  // Every file_glob in config/report_map.json must therefore START WITH '*'.
  // A glob anchored at the report name (e.g. "UnitDirectory*.xlsx") matches
  // nothing once the date is in front -- fnmatch tests the whole filename.
  PREFIX_WITH_DATE: true,

  // Where files go when no rule matches. Doubles as the retry queue:
  // resortExistingFiles re-scans it, so a new rule rescues old files.
  UNSORTED_FOLDER: '_Unsorted',

  // Max threads per run (keeps each run inside Apps Script's time limit).
  MAX_THREADS: 50,
};

/**
 * Folders that live OUTSIDE the target folder, addressed by absolute ID.
 *
 * The target folder is the Gmail filer's drop tree -- one subfolder per report
 * type, churning daily. The Drive library ("Resi Dashboard") is a different
 * thing: hand-curated, long-lived material -- keys, reference documents, the
 * unit directory -- deliberately kept out of the drop tree so automation does
 * not churn it. getSubfolder_ can only create and find folders INSIDE the
 * target folder, so a rule pointing at the library needs its ID.
 *
 * The ID is read from a Script Property, not written here: script properties
 * survive a full paste (unlike CONFIG constants -- see the SOP's warning that
 * TARGET_FOLDER_ID resets), and this file is committed to a public repo.
 * Set it once: Project Settings -> Script Properties -> Add script property,
 * name BUILDING_INFO_FOLDER_ID, value the part of the folder URL after
 * /folders/. Until it is set, matching files stay in _Unsorted and each run
 * logs why -- they are never filed into a wrong folder, and never lost.
 */
const EXTERNAL_FOLDERS = {
  'Building Info': 'BUILDING_INFO_FOLDER_ID',
};

/**
 * ROUTING RULES — the part you'll actually maintain.
 *
 * HOW MATCHING WORKS (deliberately forgiving):
 *   The filename is lowercased and ALL spaces, underscores, hyphens and dots
 *   are stripped before matching. So "Rent_Roll", "rent roll", "RENT-ROLL" and
 *   "RentRoll07_14_2026" all become "rentroll..." and hit the same rule.
 *   You do NOT need a pattern for every naming variation.
 *
 * ORDER MATTERS: the FIRST rule that matches wins. Keep specific rules above
 *   broad ones (that's why T12/expenses sits last -- /expense/ is greedy).
 *
 * If the filename matches nothing, the email SUBJECT is tried the same way.
 *
 * "folder" must match the Drive folder name EXACTLY, and must appear as a
 *   drive_folder in config/report_map.json. Apps Script CREATES a folder that
 *   doesn't exist, so a typo doesn't error -- it quietly starts a second folder
 *   the pipeline never reads. That is the failure this pairing prevents.
 */
const ROUTING_RULES = [
  { folder: 'Rent Roll',                  patterns: [/rentroll/, /rollreport/] },
  { folder: 'Concession Burnoff',         patterns: [/concession/, /burnoff/] },
  // The box score IS the property-status report (per the SOP's routing table).
  { folder: 'Property Status',            patterns: [/propertystatus/, /propstatus/, /boxscore/] },
  // Lives in the Drive library, not the drop tree -- see EXTERNAL_FOLDERS.
  { folder: 'Building Info',              patterns: [/unitdirectory/, /unitdir/] },
  // The weekly EliseAI funnel export. Its real name is
  // "leasing_funnel_report_<date>.xlsx", which contains neither "weeklyleasing"
  // nor "leasingreport" -- "funnel" sits in the middle -- so it fell through to
  // _Unsorted for six weeks. The pipeline parses funnel files from this folder
  // and from Weekly Leasing Reports, so either would work; this folder already
  // exists and already holds the EliseAI exports.
  { folder: 'EliseAI Reports',            patterns: [/leasingfunnel/, /funnelreport/, /eliseai/] },
  { folder: 'Renewal Tracker',            patterns: [/renewaltracker/, /renewalssince/, /renewalworkbook/, /renewal/] },
  { folder: 'Prospect Reports',           patterns: [/prospect/, /applicantreport/] },
  { folder: 'Daily Leasing Reports',      patterns: [/dailyreport/] },
  { folder: 'Daily Tracker',              patterns: [/dailytracker/] },
  { folder: 'Demographics',               patterns: [/demographic/] },
  // Kept for the RealPage rate tracker, this folder's intended content, which
  // has never arrived. /renewalworkbook/ moved up to Renewal Tracker.
  { folder: 'Weekly Leasing Reports',     patterns: [/weeklyleasing/, /leasingreport/, /weeklyleas/,
                                                     /leaseexpir/, /expirationreport/,
                                                     /ratetracker/, /realpage/] },
  // Was 'AIRM/Yardi Rev Management'. A slash is legal in a Drive folder name,
  // so that string did not error -- it would have created a brand-new folder
  // named "AIRM/Yardi Rev Management" beside the real one the pipeline reads.
  { folder: 'AIRM - Yardi Rev Management', patterns: [/airm/, /yardi/, /revmanagement/, /revenuemanagement/, /pricing/] },
  { folder: 'Delinquency',                patterns: [/delinquen/] },
  { folder: 'Residential AR Analytics',   patterns: [/aranalytics/, /residentialar/, /araging/, /receivable/] },
  { folder: 'AP Analytics',               patterns: [/apanalytics/, /apaging/, /accountspayable/, /payable/, /invoice/, /purchaseorder/] },
  // The trailing space and the "Mainentance" misspelling are BOTH real -- this
  // is the actual Drive folder name and the actual report_map.json key. Do not
  // tidy it here alone: renaming means the Drive folder, report_map.json and
  // this line all change together, or reports stop being read.
  { folder: 'Workorders - Mainentance ',  patterns: [/workorder/, /maintenance/, /maintaince/, /servicerequest/] },
  { folder: 'T12 Expenses',               patterns: [/t12/, /trailing12/, /expense/, /profitandloss/, /pandl/,
                                                     /monthstatement/, /incomestatement/, /operatingstatement/,
                                                     /financialstatement/] },
];
// ================================================================


/** Main job. This is the function the trigger calls. */
function fileGmailPdfsToDrive() {
  const root = getRootFolder_();
  const label = getOrCreateLabel_(CONFIG.PROCESSED_LABEL);
  const cache = {};

  const query = CONFIG.SEARCH_QUERY + ' ' + buildExtClause_(CONFIG.ALLOWED_EXTENSIONS) +
    ' -label:' + CONFIG.PROCESSED_LABEL;
  const threads = GmailApp.search(query, 0, CONFIG.MAX_THREADS);

  let saved = 0, unsorted = 0, collisions = 0;

  threads.forEach(function (thread) {
    let hadMatch = false;

    thread.getMessages().forEach(function (message) {
      const dateStr = Utilities.formatDate(
        message.getDate(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
      const subject = message.getSubject() || '';

      const attachments = message.getAttachments({
        includeInlineImages: false,
        includeAttachments: true,
      });

      attachments.forEach(function (att) {
        if (!isAllowed_(att)) return;
        hadMatch = true;

        // 1. CATEGORY IS DECIDED FIRST, from the untouched attachment name.
        //    Renaming below can never affect which folder this lands in.
        const target = routeFor_(att.getName(), subject);
        if (target === CONFIG.UNSORTED_FOLDER) unsorted++;

        // 2. Only then is the saved name worked out.
        const wanted = CONFIG.PREFIX_WITH_DATE
          ? dateStr + ' ' + att.getName()
          : att.getName();

        let dest = getSubfolder_(root, target, cache);
        if (dest === null) {   // external folder unresolved -- park it, don't guess
          dest = getSubfolder_(root, CONFIG.UNSORTED_FOLDER, cache);
          unsorted++;
        }
        const finalName = resolveName_(dest, wanted, att);

        if (finalName === null) return; // identical file already filed — skip

        dest.createFile(att.copyBlob()).setName(finalName);
        saved++;

        if (finalName !== wanted) {
          collisions++;
          Logger.log('NAME CLASH: "' + wanted + '" already existed with different ' +
            'content. Saved as "' + finalName + '" in ' + target +
            '. (Likely two properties sending the same report name.)');
        }
      });
    });

    if (hadMatch) thread.addLabel(label);
  });

  Logger.log('Filed ' + saved + ' file(s) from ' + threads.length + ' thread(s). ' +
    unsorted + ' unsorted, ' + collisions + ' name clash(es).');
}


/** Run this ONCE to schedule the job every hour. */
function createHourlyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'fileGmailPdfsToDrive') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('fileGmailPdfsToDrive').timeBased().everyHours(1).create();
  Logger.log('Hourly trigger created.');
}


/**
 * DRY RUN. Logs where every loose file in the main folder would be sent.
 * Moves nothing, renames nothing. Run this FIRST to check the rules.
 */
function previewRouting() {
  const root = getRootFolder_();
  const items = gatherResortable_(root);
  const tally = {};

  items.forEach(function (item) {
    const target = routeFor_(item.file.getName(), '');
    tally[target] = (tally[target] || 0) + 1;
    const flag = (target === item.from) ? '   (already correct)' : '';
    Logger.log(pad_(target) + ' <- ' + item.file.getName() + flag);
  });

  Logger.log('--- ' + items.length + ' file(s) previewed. Nothing was moved. ---');
  Object.keys(tally).sort().forEach(function (k) {
    Logger.log(tally[k] + ' x ' + k);
  });
}


/**
 * DRY RUN. Every rule's folder, and whether it exists in the target folder yet.
 * A rule whose folder is missing is not an error -- the folder is created on
 * first use -- but it IS how a typo or a stray slash goes unnoticed, so check
 * this list against config/report_map.json after any rename.
 */
function checkFolders() {
  const root = getRootFolder_();
  const have = {};
  const it = root.getFolders();
  while (it.hasNext()) have[it.next().getName()] = true;

  Logger.log('Target folder: ' + root.getName());
  const props = PropertiesService.getScriptProperties();
  ROUTING_RULES.forEach(function (rule) {
    const property = EXTERNAL_FOLDERS[rule.folder];
    if (property) {
      const id = props.getProperty(property);
      Logger.log((id ? 'external' : 'UNSET   ') + ' "' + rule.folder + '" (outside the ' +
        'target folder; script property ' + property + (id ? ')' : ' is NOT SET)'));
      return;
    }
    Logger.log((have[rule.folder] ? 'exists  ' : 'MISSING ') + '"' + rule.folder + '"');
  });

  const ruleNames = {};
  ROUTING_RULES.forEach(function (r) { ruleNames[r.folder] = true; });
  Object.keys(have).sort().forEach(function (name) {
    if (!ruleNames[name] && name !== CONFIG.UNSORTED_FOLDER) {
      Logger.log('no rule sends anything to "' + name + '"');
    }
  });
}


/**
 * Moves files already sitting loose in the main folder into their subfolders.
 * Run once after previewRouting looks right. Safe to re-run.
 */
function resortExistingFiles() {
  const root = getRootFolder_();
  const cache = {};
  let moved = 0, stayed = 0;

  gatherResortable_(root).forEach(function (item) {
    const target = routeFor_(item.file.getName(), '');

    // Already in the right place (incl. genuinely unidentifiable files in _Unsorted).
    if (target === item.from) { stayed++; return; }

    const dest = getSubfolder_(root, target, cache);
    if (dest === null) { stayed++; return; }   // reason already logged
    if (fileExists_(dest, item.file.getName())) { stayed++; return; }

    item.file.moveTo(dest);
    moved++;
    Logger.log('moved: ' + item.file.getName() + '   ' + item.from + ' -> ' + target);
  });

  Logger.log('Moved ' + moved + ' file(s). Left in place: ' + stayed + '.');
}


/**
 * Files eligible for (re)sorting: anything loose in the main folder, PLUS
 * anything sitting in _Unsorted — so newly added rules can rescue files that
 * were filed there before the rule existed.
 * Files already sorted into a real category folder are left alone, and files
 * OUTSIDE the target folder are invisible here.
 */
function gatherResortable_(root) {
  const out = [];

  const loose = root.getFiles();
  while (loose.hasNext()) out.push({ file: loose.next(), from: '(main folder)' });

  const it = root.getFoldersByName(CONFIG.UNSORTED_FOLDER);
  if (it.hasNext()) {
    const unsorted = it.next().getFiles();
    while (unsorted.hasNext()) {
      out.push({ file: unsorted.next(), from: CONFIG.UNSORTED_FOLDER });
    }
  }
  return out;
}


// --------------------------- routing ---------------------------

/** Strip everything that varies between naming styles. */
function normalize_(s) {
  return (s || '').toLowerCase().replace(/[\s_\-.]/g, '');
}

/** Returns the folder name for a file, or the unsorted folder. */
function routeFor_(filename, subject) {
  const haystacks = [normalize_(filename), normalize_(subject)];
  for (let h = 0; h < haystacks.length; h++) {
    if (!haystacks[h]) continue;
    for (let i = 0; i < ROUTING_RULES.length; i++) {
      const rule = ROUTING_RULES[i];
      for (let p = 0; p < rule.patterns.length; p++) {
        if (rule.patterns[p].test(haystacks[h])) return rule.folder;
      }
    }
  }
  return CONFIG.UNSORTED_FOLDER;
}


// --------------------------- helpers ---------------------------

/**
 * Decides the name to save under.
 *   - returns null  -> a byte-identical file is already there, skip it
 *   - returns name  -> free to use
 *   - returns "name (2)" -> the name was taken by DIFFERENT content, so the
 *     new report is kept alongside rather than silently dropped.
 */
function resolveName_(folder, name, att) {
  let it = folder.getFilesByName(name);
  if (!it.hasNext()) return name; // nothing there, use as-is

  const size = att.getSize();
  while (it.hasNext()) {
    if (it.next().getSize() === size) return null; // same file, already filed
  }

  // Same name, different content -> find a free suffix.
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : '';
  for (let i = 2; i < 50; i++) {
    const candidate = stem + ' (' + i + ')' + ext;
    if (!folder.getFilesByName(candidate).hasNext()) return candidate;
  }
  return stem + ' (' + Date.now() + ')' + ext;
}

function getRootFolder_() {
  if (CONFIG.TARGET_FOLDER_ID === 'PASTE_YOUR_FOLDER_ID_HERE') {
    throw new Error('Set CONFIG.TARGET_FOLDER_ID to your Drive folder ID first.');
  }
  const id = resolveFolderId_(CONFIG.TARGET_FOLDER_ID);
  try {
    return DriveApp.getFolderById(id);
  } catch (e) {
    throw new Error('Could not open the Drive folder. Check TARGET_FOLDER_ID is the ' +
      'folder ID (the part after /folders/ in the URL) and that this account can open ' +
      'it. Value used: "' + id + '"');
  }
}

/**
 * Find the destination folder for a category name.
 *
 * A name in EXTERNAL_FOLDERS is resolved by absolute ID, because it sits
 * outside the target folder. Everything else is a subfolder of the target
 * folder, created if absent. Cached per run.
 *
 * Returns null when an external folder cannot be resolved -- the caller leaves
 * the file where it is rather than creating a same-named folder inside the drop
 * tree, which would silently shadow the real one.
 */
function getSubfolder_(root, name, cache) {
  if (cache[name]) return cache[name];

  const property = EXTERNAL_FOLDERS[name];
  if (property) {
    const id = PropertiesService.getScriptProperties().getProperty(property);
    if (!id) {
      Logger.log('SKIPPED "' + name + '": it lives outside the target folder and ' +
        'script property ' + property + ' is not set, so its ID is unknown. ' +
        'Project Settings -> Script Properties -> add ' + property + '. ' +
        'Files that route here stay in ' + CONFIG.UNSORTED_FOLDER + ' meanwhile.');
      return null;
    }
    let folder;
    try {
      folder = DriveApp.getFolderById(resolveFolderId_(id));
    } catch (e) {
      Logger.log('SKIPPED "' + name + '": script property ' + property + ' is set to "' +
        id + '", which this account cannot open as a folder.');
      return null;
    }
    cache[name] = folder;
    return folder;
  }

  const it = root.getFoldersByName(name);
  const folder = it.hasNext() ? it.next() : root.createFolder(name);
  cache[name] = folder;
  return folder;
}

function isAllowed_(att) {
  const name = (att.getName() || '').toLowerCase();
  return CONFIG.ALLOWED_EXTENSIONS.some(function (ext) {
    return name.slice(-(ext.length + 1)) === '.' + ext.toLowerCase();
  });
}

function buildExtClause_(extensions) {
  return '(' + extensions.map(function (e) { return 'filename:' + e; }).join(' OR ') + ')';
}

function fileExists_(folder, name) {
  return folder.getFilesByName(name).hasNext();
}

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function resolveFolderId_(input) {
  const s = (input || '').trim();
  const m = s.match(/\/folders\/([a-zA-Z0-9_-]+)/) || s.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  return m ? m[1] : s;
}

function pad_(s) {
  return (s + '                              ').slice(0, 30);
}
