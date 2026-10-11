export const API = "/api/greedy-collector";

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, {method = "GET", body, binary = false} = {}) {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Invalid local API path");
  const options = {method, headers: {}};
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(API + path, options); }
  catch { throw new ApiError(0, "Unable to reach Greedy Collector. Check the local server and try again."); }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = typeof data?.detail === "string" ? data.detail : "";
    let message = "The request could not be completed. Please try again.";
    if (response.status === 404) message = "This address has not been stored locally yet.";
    if (response.status === 422) {
      // Only known validation messages are safe to echo; arbitrary exception text is not.
      const safeDetails = ["Invalid bitcoin address format", "Invalid ethereum address format", "Invalid TRON address format", "Invalid TRON address checksum", "Invalid public wallet address."];
      message = safeDetails.includes(detail) ? detail : "Check the selected chain and public wallet address.";
    }
    if ([429, 502, 503, 504].includes(response.status)) message = "Blockchain provider request failed. Try again later.";
    if (response.status === 502 && /provider configuration is unavailable/i.test(detail)) message = detail;
    if (response.status === 502 && /(?:ETHERSCAN_API_KEY|ALCHEMY_API_KEY)/i.test(detail)) message = "Blockchain provider configuration is unavailable.";
    if (path.startsWith("/sanctions/")) {
      if (response.status === 409) message = "OFAC synchronization is already running.";
      else if (response.status === 502) message = "OFAC synchronization failed. The previous snapshot remains available.";
      else if (response.status === 503) message = "Sanctions registry storage is unavailable.";
    }
    throw new ApiError(response.status, message);
  }
  if (binary) return response.blob();
  try { return await response.json(); }
  catch { throw new ApiError(500, "The server returned an unexpected response."); }
}
