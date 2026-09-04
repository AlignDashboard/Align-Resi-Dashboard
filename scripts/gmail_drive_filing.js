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
  // Before 'T12 Expenses': its /expense/ pattern would otherwise claim a
  // budget export whose name happens to mention expenses.
  { folder: 'Budgets',                    patterns: [/budget/] },
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

/**
 * NEW REPORT TYPES MAKE THEIR OWN FOLDER.
 *
 * A report matching no rule used to land in _Unsorted, where four weeks of
 * arrivals once piled up unnoticed. Instead, its filename is boiled down to a
 * report type and that becomes a folder. New types are visible and grouped from
 * the first email, and promoting one to a real feed is then: add a rule here,
 * add an entry to config/report_map.json, write a parser.
 *
 * The name is a starting point, not an answer. It is derived, so it can be
 * clumsy ("Renewals", "rs sql JPM Demographics Combined") and two spellings of
 * one report can make two folders. Both are fixed the same way -- add a routing
 * rule naming the folder you want -- and the fix is visible because the folders
 * are sitting there. That is the trade: a slightly untidy Drive you can see,
 * rather than a tidy _Unsorted you cannot.
 *
 * Set ENABLED false to go back to everything unmatched landing in _Unsorted.
 */
const AUTO_FOLDER = {
  ENABLED: true,

  // A cap, so a mailbox full of one-off attachments cannot carpet the drop tree
  // in a single run. Past it, files park in _Unsorted and the log says so.
  MAX_NEW_PER_RUN: 5,

  // Names never auto-created, whatever a filename boils down to.
  NEVER: ['_Unsorted', 'Archive Reports', 'Report Lander'],
};

/**
 * Property names, aliases and codes, stripped out before naming a report type
 * -- "8.30.26 - The Madelon - Daily Report" is a Daily Report, not a Madelon
 * report. Generated from config/properties.json; scripts/test_routing.py fails
 * if the two drift apart.
 */
const PROPERTY_WORDS = [
  "Sequoia Living Project", "Walnut Creek Center", "Sequoia Living Inc", "335 Third Street",
  "California Plaza", "3350 Mission St", "15 Marina Blvd", "335 3rd Street",
  "Burbank Empire", "1023 Mission", "1335 Webster", "2101 Mission",
  "5727 College", "850 La Playa", "Essex PropCo", "The Exchange",
  "123 Mission", "667 Mission", "Align So FS", "The Landing",
  "The Madelon", "Wood Hollow", "Essex OpCo", "Livermore",
  "dnccasofs", ".Landing", "1655 ECR", "251 Post",
  "Bellevue", "camadelo", "camadret", "dnc1335w",
  "dnc15mar", "dnc1655e", "dnc3350m", "dnc5727c",
  "dnc850la", "dncsequi", "dncsequo", "esx00141",
  "esx00142", "esx00143", "esx00144", "esx00145",
  "esx00146", "esx00147", "esx00149", "exc00130",
  "p0003872", "p0004764", "p0005215", "p0005611",
  "p0005612", "p0005640", "p0005671", "rspalman",
  "rspalmas", ".Chorus", "1023070", "1230090",
  "2101121", "2101122", "2101123", "2510150",
  "6670040", "Madelon", "WCC0050", "bec0100",
  "bec0101", "bec0102", "bpc0010", "cp00080",
  "lm00030", "lm00031", "lm00032", "lm00033",
  "madelon", "owcc051", "p000611", "twcc052",
  "wh00020", ".palma", "Chorus", "Palma",
  "rs335",
];

const AUTO_EXTS = ['xlsx', 'xls', 'csv', 'pdf', 'docx', 'doc'];
const AUTO_FILLER = /(?:^|\s)(week ending|weekending|as of|since|thru|through|updated|copy of)(?=\s|$)/gi;

/**
 * Boil a filename down to the report type it represents, or '' if it cannot be
 * named. Order matters throughout -- see the comment on each step.
 */
function reportTypeFor_(filename) {
  var s = String(filename || '');

  // Repeated, because real files carry doubled extensions: "….xls.xlsx".
  for (var i = 0; i < 3; i++) {
    var m = s.match(/\.([A-Za-z0-9]+)$/);
    if (m && AUTO_EXTS.indexOf(m[1].toLowerCase()) !== -1) s = s.slice(0, m.index);
    else break;
  }

  s = s.replace(/^\d{4}-\d{2}-\d{2}\s+/, '');   // the date this filer prefixed
  s = s.replace(/\([^)]*\d[^)]*\)/g, ' ');       // "(1)", "(1a)", "(updated 8.30.26)"
  s = s.replace(/_+/g, ' ');                      // BEFORE any \b rule: _ is a word char
  s = s.replace(/([A-Za-z])(\d)/g, '$1 $2');      // "RentRoll07" -> "RentRoll 07"
  s = s.replace(/\b\d+\s*Days?\b/gi, ' ');       // 30Days / 60Days: one report, two windows

  for (var p = 0; p < PROPERTY_WORDS.length; p++) {
    s = s.replace(new RegExp('\\b' + PROPERTY_WORDS[p].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      + '\\b', 'gi'), ' ');
  }

  // Three passes because dates come in ranges: "08.24.2026- 08.30.2026".
  for (var d = 0; d < 3; d++) {
    s = s.replace(/\b\d{1,4}[._\-\/]\d{1,2}(?:[._\-\/]\d{1,4})?\b/g, ' ');
  }
  s = s.replace(/\b\d{1,8}\b/g, ' ');            // whatever number is left is date debris
  s = s.replace(/\s*[-–—]+\s*/g, ' ');
  s = s.replace(/\s{2,}/g, ' ').replace(/^[\s\-–—_.]+|[\s\-–—_.]+$/g, '');
  s = s.replace(AUTO_FILLER, ' ');
  s = s.replace(/\s{2,}/g, ' ').replace(/^[\s\-–—_.]+|[\s\-–—_.]+$/g, '');

  // Too short, or no real word in it, means we are guessing. Say so instead.
  if (s.length < 4 || !/[A-Za-z]{3}/.test(s)) return '';
  if (AUTO_FOLDER.NEVER.indexOf(s) !== -1) return '';
  return s.slice(0, 60).replace(/[\s\-–—_.]+$/, '');
}



/** Main job. This is the function the trigger calls. */
function fileGmailPdfsToDrive() {
  AUTO_STATE.created = 0;
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

  const have = {};
  const walk = root.getFolders();
  while (walk.hasNext()) have[normalize_(walk.next().getName())] = true;

  items.forEach(function (item) {
    const target = routeFor_(item.file.getName(), '');
    tally[target] = (tally[target] || 0) + 1;
    var flag = (target === item.from) ? '   (already correct)' : '';
    if (!have[normalize_(target)]) flag += '   [NEW FOLDER]';
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
  AUTO_STATE.created = 0;
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
  // No rule matched. Name the report type from the filename so it gets its own
  // folder. This is PURE -- it returns a name and creates nothing, so
  // previewRouting can show what would happen without touching Drive.
  if (AUTO_FOLDER.ENABLED) {
    var derived = reportTypeFor_(filename) || reportTypeFor_(subject);
    if (derived) return derived;
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
  if (it.hasNext()) {
    cache[name] = it.next();
    return cache[name];
  }

  // The folder does not exist. If a rule asked for it, create it as always --
  // that is the long-standing behaviour and the rule is a deliberate decision.
  const fromRule = ROUTING_RULES.some(function (r) { return r.folder === name; });
  if (fromRule || !AUTO_FOLDER.ENABLED || name === CONFIG.UNSORTED_FOLDER) {
    cache[name] = root.createFolder(name);
    return cache[name];
  }

  // An auto-derived name. Before making a folder, see whether one already there
  // means the same thing -- "Daily report" and "Daily Report" are one type, and
  // silently splitting them is how a drop tree turns into a junk drawer.
  const wanted = normalize_(name);
  const existing = root.getFolders();
  while (existing.hasNext()) {
    const f = existing.next();
    if (normalize_(f.getName()) === wanted) {
      Logger.log('auto-folder: "' + name + '" matches the existing "' + f.getName() +
        '" — filing there rather than making a second one');
      cache[name] = f;
      return cache[name];
    }
  }

  if (AUTO_STATE.created >= AUTO_FOLDER.MAX_NEW_PER_RUN) {
    Logger.log('auto-folder: already made ' + AUTO_STATE.created + ' new folder(s) this ' +
      'run, so "' + name + '" goes to ' + CONFIG.UNSORTED_FOLDER + ' instead. Raise ' +
      'AUTO_FOLDER.MAX_NEW_PER_RUN or run again.');
    return getSubfolder_(root, CONFIG.UNSORTED_FOLDER, cache);
  }

  AUTO_STATE.created++;
  Logger.log('auto-folder: NEW REPORT TYPE "' + name + '" — created a folder for it. ' +
    'Add a rule and a config/report_map.json entry to make it a real feed.');
  cache[name] = root.createFolder(name);
  return cache[name];
}

// Reset per run by the entry points, so the cap counts one execution.
var AUTO_STATE = { created: 0 };

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
