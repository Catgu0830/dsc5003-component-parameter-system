
// ========================================
// User Authentication Module
// ========================================

document.addEventListener("DOMContentLoaded", () => {

    const loginForm = document.getElementById("loginForm");
    const loginButton = document.getElementById("loginButton");
    const loginMessage = document.getElementById("loginMessage");

    // ------------------------------------
    // Login Form Submission
    // ------------------------------------

    loginForm.addEventListener("submit", async (event) => {

        event.preventDefault();

        const username = document
            .getElementById("username")
            .value.trim();

        const password = document
            .getElementById("password")
            .value;

        // Reset message
        loginMessage.textContent = "";
        loginMessage.className = "message";

        // Validate input
        if (!username || !password) {

            loginMessage.textContent =
                "Please enter both username and password.";

            loginMessage.className = "message error";

            return;

        }

        // Loading state
        loginButton.disabled = true;
        loginButton.textContent = "Signing In...";

        try {

            // Call Member C authentication API
            const result = await apiRequest(
                "/api/auth/login",
                {
                    method: "POST",
                    auth: false,
                    body: {
                        username: username,
                        password: password
                    }
                }
            );

            const data = result.data;

            // Validate returned token
            if (!data || !data.token) {

                throw new Error(
                    "The server did not return a valid authentication token."
                );

            }

            // Save authentication token
            saveToken(data.token);

            // Save user information
            if (data.user) {

                localStorage.setItem(
                    "currentUser",
                    JSON.stringify(data.user)
                );

            }

            // Success message
            loginMessage.textContent =
                "Login successful! Redirecting to Dashboard...";

            loginMessage.className = "message success";

            // Redirect to Dashboard
            window.setTimeout(() => {

                window.location.href = "pages/dashboard.html";

            }, 500);

        } catch (error) {

            console.error("Login error:", error);

            // Display English error messages
            const message = error.message || "";

            let displayMessage =
                "Sign-in failed. Please check your credentials and try again.";

            if (
                message.includes("401") ||
                message.toLowerCase().includes("unauthorized")
            ) {

                displayMessage =
                    "Invalid username or password.";

            } else if (
                message.toLowerCase().includes("failed to fetch") ||
                message.toLowerCase().includes("networkerror")
            ) {

                displayMessage =
                    "Unable to connect to the server. Please check whether the backend is running.";

            } else if (
                message.includes("valid authentication token")
            ) {

                displayMessage =
                    "Authentication failed. The server returned an invalid token.";

            }

            loginMessage.textContent = displayMessage;

            loginMessage.className = "message error";

        } finally {

            // Restore button
            loginButton.disabled = false;
            loginButton.textContent = "Sign In";

        }

    });

});
