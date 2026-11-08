import { createResource } from "frappe-ui"

// What the SLHRM app may show the session user. The server enforces the same rules
// (Employee Checkin before_insert / validate), so this only controls visibility.
export const appPermissions = createResource({
	url: "slhrm.api.get_app_permissions",
	cache: "slhrm:app_permissions",
})
