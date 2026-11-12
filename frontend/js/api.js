
// ========================================
// API Request Module
// Backend: Flask + SQLite
// ========================================

const API_BASE_URL = "http://127.0.0.1:5000";

// ------------------------------------
// Authentication Token Management
// ------------------------------------

// Get current authentication token
function getToken() {
    return localStorage.getItem("token");
}

// Save authentication token
function saveToken(token) {
    localStorage.setItem("token", token);
}

// Clear authentication information
function clearAuth() {
    localStorage.removeItem("token");
    localStorage.removeItem("currentUser");
}

// ------------------------------------
// API Error Handling
// ------------------------------------

function getEnglishErrorMessage(result, status) {

    const fallback = `Request failed (HTTP ${status}). Please try again.`;

    if (typeof result === "object" && result !== null) {

        const message = String(result.message || "");

        // Preserve already-English server messages
        if (message && !/[\u4e00-\u9fff]/.test(message)) {
            return message;
        }

        // Use an English fallback for Chinese server messages
        if (message) {
            return fallback;
        }

    }

    if (typeof result === "string" && result.trim()) {

        if (!/[\u4e00-\u9fff]/.test(result)) {
            return result;
        }

    }

    return fallback;
}

// ------------------------------------
// Unified API Request Function
// ------------------------------------

async function apiRequest(path, options = {}) {

    const {
        method = "GET",
        body,
        auth = true,
        headers = {}
    } = options;

    const requestHeaders = { ...headers };

    // Automatically set JSON Content-Type
    if (
        body !== undefined &&
        !(body instanceof FormData)
    ) {
        requestHeaders["Content-Type"] = "application/json";
    }

    // Automatically attach authentication token
    const token = getToken();

    if (auth && token) {
        requestHeaders["Authorization"] = `Bearer ${token}`;
    }

    // Send API request
    const response = await fetch(
        `${API_BASE_URL}${path}`,
        {
            method,
            headers: requestHeaders,
            body: body === undefined
                ? undefined
                : body instanceof FormData
                    ? body
                    : JSON.stringify(body)
        }
    );

    // Parse response
    const contentType =
        response.headers.get("content-type") || "";

    let result;

    if (contentType.includes("application/json")) {

        result = await response.json();

    } else {

        result = await response.text();

    }

    // ------------------------------------
    // HTTP Error Handling
    // ------------------------------------

    if (!response.ok) {

        if (response.status === 401 && auth) {
            clearAuth();
        }

        console.error(
            "API Error:",
            response.status,
            result
        );

        throw new Error(
            getEnglishErrorMessage(result, response.status)
        );

    }

    // ------------------------------------
    // Application-Level Error Handling
    // ------------------------------------

    if (
        typeof result === "object" &&
        result !== null &&
        result.code !== undefined &&
        result.code !== 0
    ) {

        console.error("API Application Error:", result);

        throw new Error(
            getEnglishErrorMessage(result, response.status)
        );

    }

    // Return successful response
    return result;

}
