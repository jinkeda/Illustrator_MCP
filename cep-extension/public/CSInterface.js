/**
 * CSInterface - Adobe Common Extensibility Platform Interface
 * 
 * This is a minimal implementation of the CSInterface library for CEP extensions.
 * For production use, download the full version from:
 * https://github.com/Adobe-CEP/CEP-Resources
 */

function CSInterface() {
    this.hostEnvironment = null;
}

/**
 * Evaluates a JavaScript script in the host application's ExtendScript context.
 * @param {string} script - The JavaScript code to evaluate
 * @param {function} callback - Callback function to receive the result
 */
CSInterface.prototype.evalScript = function (script, callback) {
    if (callback === null || callback === undefined) {
        callback = function (result) { };
    }

    // Use window.__adobe_cep__ if available (CEP runtime)
    if (window.__adobe_cep__) {
        window.__adobe_cep__.evalScript(script, callback);
    } else {
        // Fallback for testing outside CEP
        console.warn('CSInterface: Not running in CEP environment');
        callback('{"error": "Not running in CEP environment"}');
    }
};

/**
 * Gets the host environment information.
 * @returns {object} Host environment info
 */
CSInterface.prototype.getHostEnvironment = function () {
    if (this.hostEnvironment) {
        return this.hostEnvironment;
    }

    if (window.__adobe_cep__) {
        this.hostEnvironment = JSON.parse(window.__adobe_cep__.getHostEnvironment());
    } else {
        this.hostEnvironment = {
            appName: 'Unknown',
            appVersion: '0.0',
            appLocale: 'en_US',
            appUILocale: 'en_US',
            appId: 'ILST',
            isAppOnline: true
        };
    }

    return this.hostEnvironment;
};

/**
 * Gets the system path for the specified type.
 * @param {string} pathType - Type of path to get
 * @returns {string} The system path
 */
CSInterface.prototype.getSystemPath = function (pathType) {
    if (window.__adobe_cep__) {
        return window.__adobe_cep__.getSystemPath(pathType);
    }
    return '';
};

/**
 * Opens a URL in the default browser.
 * @param {string} url - The URL to open
 */
CSInterface.prototype.openURLInDefaultBrowser = function (url) {
    if (window.__adobe_cep__) {
        window.__adobe_cep__.openURLInDefaultBrowser(url);
    } else {
        window.open(url, '_blank');
    }
};

/**
 * Registers an event listener for CEP events.
 * @param {string} type - Event type
 * @param {function} listener - Event handler
 * @param {object} obj - Context object
 */
CSInterface.prototype.addEventListener = function (type, listener, obj) {
    if (window.__adobe_cep__) {
        window.__adobe_cep__.addEventListener(type, listener, obj);
    }
};

/**
 * Removes an event listener.
 * @param {string} type - Event type
 * @param {function} listener - Event handler
 * @param {object} obj - Context object
 */
CSInterface.prototype.removeEventListener = function (type, listener, obj) {
    if (window.__adobe_cep__) {
        window.__adobe_cep__.removeEventListener(type, listener, obj);
    }
};

/**
 * Dispatches an event to the host application.
 * @param {object} event - Event to dispatch
 */
CSInterface.prototype.dispatchEvent = function (event) {
    if (window.__adobe_cep__) {
        window.__adobe_cep__.dispatchEvent(event);
    }
};

/**
 * Closes this extension panel.
 */
CSInterface.prototype.closeExtension = function () {
    if (window.__adobe_cep__) {
        window.__adobe_cep__.closeExtension();
    }
};

/**
 * Gets the current extension ID.
 * @returns {string} Extension ID
 */
CSInterface.prototype.getExtensionID = function () {
    if (window.__adobe_cep__) {
        return window.__adobe_cep__.getExtensionId();
    }
    return 'com.illustrator.mcp.panel';
};

// SystemPath constants
CSInterface.prototype.SYSTEM_PATH = {
    USER_DATA: 'userData',
    COMMON_FILES: 'commonFiles',
    MY_DOCUMENTS: 'myDocuments',
    APPLICATION: 'application',
    EXTENSION: 'extension',
    HOST_APPLICATION: 'hostApplication'
};
