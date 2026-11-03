// JSON client for /api. Every state-changing call carries the CSRF header.

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
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
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, json = {}) => request("POST", path, { json }),
  put: (path, json = {}) => request("PUT", path, { json }),
  del: (path) => request("DELETE", path),
  upload: (path, file, method = "POST") => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request(method, path, { form });
  },
  // A plain link the browser can follow (downloads rely on the session cookie).
  url: (path) => `/api${path}`,
};
