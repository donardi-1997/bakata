// Restrict path components across Windows and POSIX; callers create directories exclusively.
export function validReportId(value) {
  return /^[a-zA-Z0-9_-]{1,80}$/.test(value)
    && !/^(con|prn|aux|nul|conin_|conout_|com[1-9]|lpt[1-9])$/i.test(value);
}
