// Public registration for the standard user role.

document.addEventListener("DOMContentLoaded", () => {

    if (getToken()) {
        window.location.href = "pages/dashboard.html";
        return;
    }

    const form = document.getElementById("registerForm");
    const button = document.getElementById("registerButton");
    const message = document.getElementById("registerMessage");

    function show(text, type = "error") {
        message.textContent = text;
        message.className = "message " + type;
    }

    form.addEventListener("submit", async event => {

        event.preventDefault();

        const username = document.getElementById("username").value.trim();
        const password = document.getElementById("password").value;
        const confirmPassword = document.getElementById("confirmPassword").value;

        if (!username || !password) {
            show("Please enter a username and password.");
            return;
        }

        if (password !== confirmPassword) {
            show("The two passwords do not match.");
            return;
        }

        button.disabled = true;
        button.textContent = "Creating...";

        try {

            await apiRequest("/api/auth/register", {
                method: "POST",
                auth: false,
                body: { username, password }
            });

            show("Account created. Redirecting to sign in...", "success");

            window.setTimeout(() => {
                window.location.href = "login.html";
            }, 700);

        } catch (error) {

            show(error.message || "Registration failed.");

        } finally {

            button.disabled = false;
            button.textContent = "Create Account";

        }

    });

});
