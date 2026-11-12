
// ========================================
// Dashboard Module
// ========================================

document.addEventListener("DOMContentLoaded", async () => {

    const token = getToken();

    // Redirect to login if not authenticated
    if (!token) {
        window.location.href = "../login.html";
        return;
    }

    const userName = document.getElementById("userName");
    const currentRole = document.getElementById("currentRole");
    const componentCount = document.getElementById("componentCount");
    const componentTable = document.getElementById("componentTable");
    const logoutButton = document.getElementById("logoutButton");
    const systemStatus = document.getElementById("systemStatus");

    // Load user information and components
    try {

        const [userResult, componentResult] = await Promise.all([
            apiRequest("/api/auth/me"),
            apiRequest("/api/components?page=1&page_size=6")
        ]);

        const user = userResult.data.user || userResult.data;

        // User role translations
        const roleNames = {
            admin: "Administrator",
            auditor: "Auditor",
            user: "User"
        };

        userName.textContent =
            `Welcome, ${user.username || "User"}`;

        currentRole.textContent =
            roleNames[user.role] || user.role || "Unknown";

        // Component statistics
        const data = componentResult.data;

        componentCount.textContent = data.total ?? 0;

        // Render component list
        const components = data.items || [];

        componentTable.innerHTML = "";

        if (components.length === 0) {

            componentTable.innerHTML = `
                <tr>
                    <td colspan="4" class="empty-message">
                        No component data available.
                    </td>
                </tr>
            `;

        } else {

            components.forEach(component => {

                const row = document.createElement("tr");

                const values = [
                    component.model,
                    component.manufacturer,
                    component.category,
                    (component.parameters || []).length
                ];

                values.forEach(value => {

                    const cell = document.createElement("td");

                    // Use textContent to prevent unsafe HTML injection
                    cell.textContent = value ?? "-";

                    row.appendChild(cell);

                });

                componentTable.appendChild(row);

            });

        }

        systemStatus.textContent = "Normal";

    } catch (error) {

        console.error("Dashboard error:", error);

        if (error.message.includes("401")) {

            clearAuth();

            window.location.href = "../login.html";

            return;

        }

        componentTable.innerHTML = `
            <tr>
                <td colspan="4" class="empty-message">
                    Failed to load component data.
                </td>
            </tr>
        `;

        componentCount.textContent = "-";

        systemStatus.textContent = "Error";

        userName.textContent = "Unable to load user information.";

    }

    // Logout functionality
    logoutButton.addEventListener("click", async () => {

        logoutButton.disabled = true;

        logoutButton.textContent = "Logging out...";

        try {

            await apiRequest("/api/auth/logout", {
                method: "POST"
            });

        } catch (error) {

            console.error("Logout error:", error);

        } finally {

            clearAuth();

            window.location.href = "../login.html";

        }

    });

});
