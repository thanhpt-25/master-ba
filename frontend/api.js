// JSON client for /api. Every state-changing call carries the CSRF header.

import { usageLimitText } from "./dom.js";
import { t } from "./i18n.js";

export class ApiError extends Error {
  constructor(status, detail, data = null) {
    super(detail);
    this.status = status;
    this.data = data; // the structured detail, e.g. a usage limit (spec 23)
  }
}

// FastAPI validation errors (422) as one readable sentence: which field, and what is wrong.
export function validationText(errors) {
  return errors.map((error) => {
    const field = (error.loc ?? []).filter((part) => part !== "body").join(".");
    const what = error.type === "string_pattern_mismatch"
      ? t("uses characters that are not allowed")
      : error.type === "missing" ? t("is required") : String(error.msg ?? "");
    return field ? t("{field} {what}", { field, what }) : what;
  }).join(" ");
}

async function request(method, path, { json, form } = {}) {
  const headers = { "X-MasterBA": "1" };
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  const response = await fetch(`/api${path}`, { method, headers, body, credentials: "same-origin" });
  if (!response.ok) {
    let detail = response.statusText;
    let data = null;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail?.code === "usage_limit") {
        data = body.detail;
        detail = usageLimitText(body.detail);
      } else if (Array.isArray(body.detail)) detail = validationText(body.detail);
      else detail = JSON.stringify(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, detail, data);
  }
  return response.json();
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, json = {}) => request("POST", path, { json }),
  put: (path, json = {}) => request("PUT", path, { json }),
  patch: (path, json = {}) => request("PATCH", path, { json }),
  del: (path) => request("DELETE", path),
  upload: (path, file, method = "POST") => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request(method, path, { form });
  },
  // A plain link the browser can follow (downloads rely on the session cookie).
  url: (path) => `/api${path}`,
};
