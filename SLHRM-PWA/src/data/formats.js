// Number / currency display settings from the /slhrm boot page (slhrm/www/slhrm.py get_formats).
// The Employee role may not read System Settings, so never fetch them from the API.
const DEFAULTS = {
	number_format: "#,###.##",
	currency_precision: 2,
	float_precision: 3,
	country: "",
	language: "en",
}

export function bootFormats() {
	return { ...DEFAULTS, ...(window.frappe?.boot?.slhrm_formats || {}) }
}
