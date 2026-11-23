// palette.js isRelative (thread_store.js isRelativePath): a same-site path only, never "//host", a backslash form or a
// scheme. The palette uses it for the href of a row and for the path a row opens; a path that fails it does nothing.
const RELATIVE_PATH = /^\/(?![/\\])[^\x00-\x20\x7f]*$/;

export function isRelativePath(path: string | null | undefined): path is string {
  return typeof path === "string" && RELATIVE_PATH.test(path);
}
