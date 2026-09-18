const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(endpoint, options = {}) {
  const controller = new AbortController();

  const timeout = setTimeout(() => {
    controller.abort();
  }, 30000);

  try {
    const response = await fetch(
      `${API_BASE_URL}${endpoint}`,
      {
        ...options,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      }
    );

    if (!response.ok) {
      let message = `API request failed with status ${response.status}`;

      try {
        const errorData = await response.json();

        if (errorData?.detail) {
          message = errorData.detail;
        } else if (errorData?.message) {
          message = errorData.message;
        }
      } catch {
        // Keep default message.
      }

      throw new Error(message);
    }

    return response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The API request timed out.");
    }

    if (error instanceof TypeError) {
      throw new Error(
        "Unable to connect to the FastAPI server. Make sure it is running on port 8000."
      );
    }

    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function buildQuery(params = {}) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (
      value !== undefined &&
      value !== null &&
      String(value).trim() !== ""
    ) {
      query.set(key, String(value));
    }
  });

  return query.toString();
}

export async function getSuppliers(params = {}) {
  const query = buildQuery(params);

  return request(
    `/api/suppliers${query ? `?${query}` : ""}`
  );
}

export async function getSupplier(id) {
  return request(
    `/api/suppliers/${encodeURIComponent(id)}`
  );
}

export async function getStates() {
  return request("/api/states");
}

export async function getDistricts(state = "") {
  const query = buildQuery({ state });

  return request(
    `/api/districts${query ? `?${query}` : ""}`
  );
}

export async function getStats() {
  return request("/api/stats");
}

export async function checkHealth() {
  return request("/health");
}

export { API_BASE_URL };