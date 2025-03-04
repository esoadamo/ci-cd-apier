class Apier {
    /**
     * Initialize Apier for communication with GitLab CI/CD pipeline
     * @param age_ci_public_key {string} - Public key for AGE encryption
     * @param gitlab_pipeline_endpoint {string} - GitLab pipeline endpoint
     * @param gitlab_token {string} - GitLab pipeline token
     * @param gitlab_branch {string} - GitLab branch, default is 'main'
     * @param max_data_size {number} - Maximum data size for a single request, default is 100 kilobytes
     */
    constructor(age_ci_public_key, gitlab_pipeline_endpoint, gitlab_token, gitlab_branch = 'main', max_data_size = 102400) {
        this.__loaded = false;
        this.__age_local = null;
        this.__age_ci_public_key = age_ci_public_key;
        this.__pipeline_endpoint = gitlab_pipeline_endpoint;
        this.__gitlab_token = gitlab_token;
        this.__gitlab_branch = gitlab_branch;
        this.__max_data_size = max_data_size;
    }

    /**
     * Send request to GitLab CI/CD pipeline
     * @param path {string} - Virtual path to the API endpoint
     * @param data {object} - Data to be sent to the API endpoint
     * @param timeout {number} - Timeout in seconds, default is 300 seconds
     * @returns {Promise<unknown>} - Response from the API endpoint
     */
    async sendRequest(path, data, timeout = 300) {
        await this.__loadApier();

        const requestId = this.constructor.__uuid();
        const requestData = {
            'id': requestId,
            'data': data,
            'path': path,
            'age_public_key': this.__age_local.publicKey
        };

        const requestDataJson = JSON.stringify(requestData);
        const encryptedRequestData = encrypt(this.__age_ci_public_key, requestDataJson);

        if (encryptedRequestData.error) {
            throw new Error(encryptedRequestData.error);
        }

        /** @type {string} */
        const encryptedData = encryptedRequestData.output;
        const dataRequests = [];
        const maxDataSize = this.__max_data_size - 100;  // 100 bytes for metadata
        if (encryptedData.length < maxDataSize) {
            dataRequests.push(encryptedData);
        } else {
            const parts = Math.ceil(encryptedData.length / maxDataSize);
            for (let i = 0; i < parts; i++) {
                const part= encryptedData.substring(i * maxDataSize, (i + 1) * maxDataSize);
                dataRequests.push(`MP_${requestId}_${i + 1}_${parts}_${part}`);
            }
        }

        // Send all parts to the pipeline, one by one. Only one if the data is small enough
        for (let i = 0; i < dataRequests.length; i++) {
            const dataRequest = dataRequests[i];
            const formData = new FormData();
            formData.append('token', this.__gitlab_token);
            formData.append('ref', this.__gitlab_branch);
            formData.append('variables[APIER_DATA]', dataRequest);

            const req = await fetch(this.__pipeline_endpoint, {
                method: 'POST',
                body: formData
            });

            if (!req.ok) {
                throw new Error(`Failed to send request to ${this.__pipeline_endpoint}`);
            }
            if (i < dataRequests.length - 1) {
                await new Promise(resolve => setTimeout(resolve, 1000 + Math.floor(Math.random() * 1000)));
            }
        }

        const responseURL = `apier-responses/${requestId}.txt`;

        return new Promise((resolve, reject) => {
            let responseTimeout = null;
            let responseCheck = null;
            const dateStart = Date.now() / 1000;
            const privateKey = this.__age_local.privateKey;

            function scheduleResponseCheck() {
                responseCheck = setTimeout(
                    async () => {
                        const responseReq = await fetch(responseURL);
                        if (responseReq.ok) {
                            clearTimeout(responseTimeout);
                            const response = await responseReq.text();
                            const decryptedResponseJSON = decrypt(privateKey, response);
                            if (decryptedResponseJSON.error) {
                                reject(new Error(decryptedResponseJSON.error));
                            }

                            const decryptedResponse = JSON.parse(decryptedResponseJSON.output);
                            if (decryptedResponse.status !== 'success') {
                                reject(decryptedResponse);
                            }

                            resolve(decryptedResponse.data);
                        } else {
                            scheduleResponseCheck();
                        }
                    }, (Date.now() / 1000 - dateStart) < (dataRequests.length * 45) ? 15000 : 3500);
            }
            scheduleResponseCheck();

            responseTimeout = setTimeout(() => {
                if (responseCheck !== null) {
                    clearTimeout(responseCheck);
                }
                reject(new Error(`Request timeout for ${responseURL}`));
            }, timeout * dataRequests.length * 1000);
        });
    }

    /**
     * Load AGE WASM module
     * @returns {Promise<void>} - Resolve when the module is loaded
     * @private
     */
    async __loadApier() {
        if (this.__loaded) {
            return;
        }

        const go = new Go();
        const result = await WebAssembly.instantiateStreaming(fetch("apier/agewasm/age.wasm"), go.importObject);
        go.run(result.instance).then(() => console.log("AGE WASM module exited"));
        this.__age_local = generateX25519Identity();
        this.__loaded = true;
    }

    /**
     * Generate UUID
     * @returns {`${string}-${string}-${string}-${string}-${string}`|string}
     * @private
     */
    static __uuid() {
        try {
            return crypto.randomUUID();
        } catch (e) {
            // https://stackoverflow.com/questions/105034/how-do-i-create-a-guid-uuid#2117523
            function uuidv4() {
                return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c =>
                    (+c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> +c / 4).toString(16)
                );
            }

            return uuidv4();
        }
    }

    /**
     * Initialize Apier from well-known config file
     * @returns {Promise<Apier>} - Apier instance
     */
    static auto() {
        return fetch('apier/client.json').then(
            async (response) => {
                if (!response.ok) {
                    throw new Error(`Failed to load apier/client.json`);
                }
                /** @type {{age_public_key: string, gitlab_pipeline_endpoint: string, gitlab_token: string, gitlab_branch: string | null}} */
                const config = await response.json();
                return new Apier(config.age_public_key, config.gitlab_pipeline_endpoint, config.gitlab_token, config.gitlab_branch || undefined);
            }
        )
    }
}
