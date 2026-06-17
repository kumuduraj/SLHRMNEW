import { isPlatform, createAnimation } from "@ionic/vue"

const animationBuilder = (baseEl, opts) => {
	if (opts.direction === "back") {
		return createAnimation()
	}
	return undefined
}

const getIonicConfig = () => {
	const config = { mode: "ios" }

	if (isPlatform("iphone")) {
		config.swipeBackEnabled = false
		config.navAnimation = animationBuilder
	}

	return config
}

export default getIonicConfig
