const STORAGE_KEY = 'mcp_logger_config';
/**
 * Chrome Storage-based logger persistence
 */
export class LoggerStorage {
    storageKey;
    constructor(storageKey = STORAGE_KEY) {
        this.storageKey = storageKey;
    }
    /**
     * Get the global log level from storage
     */
    async getLevel() {
        try {
            if (typeof chrome === 'undefined' || !chrome.storage) {
                return null;
            }
            const result = await chrome.storage.local.get(this.storageKey);
            const config = result[this.storageKey];
            if (config && typeof config.level === 'number') {
                return config.level;
            }
            return null;
        }
        catch (error) {
            console.error('[LoggerStorage] Failed to get level:', error);
            return null;
        }
    }
    /**
     * Set the global log level in storage
     */
    async setLevel(level) {
        try {
            if (typeof chrome === 'undefined' || !chrome.storage) {
                return;
            }
            const existing = await chrome.storage.local.get(this.storageKey);
            const config = existing[this.storageKey] || {};
            config.level = level;
            await chrome.storage.local.set({ [this.storageKey]: config });
        }
        catch (error) {
            console.error('[LoggerStorage] Failed to set level:', error);
        }
    }
    /**
     * Get component-specific log levels from storage
     */
    async getComponentLevels() {
        try {
            if (typeof chrome === 'undefined' || !chrome.storage) {
                return {};
            }
            const result = await chrome.storage.local.get(this.storageKey);
            const config = result[this.storageKey];
            if (config && config.componentLevels) {
                return config.componentLevels;
            }
            return {};
        }
        catch (error) {
            console.error('[LoggerStorage] Failed to get component levels:', error);
            return {};
        }
    }
    /**
     * Set a component-specific log level in storage
     */
    async setComponentLevel(component, level) {
        try {
            if (typeof chrome === 'undefined' || !chrome.storage) {
                return;
            }
            const existing = await chrome.storage.local.get(this.storageKey);
            const config = existing[this.storageKey] || {};
            if (!config.componentLevels) {
                config.componentLevels = {};
            }
            config.componentLevels[component] = level;
            await chrome.storage.local.set({ [this.storageKey]: config });
        }
        catch (error) {
            console.error('[LoggerStorage] Failed to set component level:', error);
        }
    }
    /**
     * Clear all logger configuration from storage
     */
    async clear() {
        try {
            if (typeof chrome === 'undefined' || !chrome.storage) {
                return;
            }
            await chrome.storage.local.remove(this.storageKey);
        }
        catch (error) {
            console.error('[LoggerStorage] Failed to clear storage:', error);
        }
    }
}
