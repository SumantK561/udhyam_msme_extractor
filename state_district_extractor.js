(async () => {

    const stateSelect = document.querySelector("#State");
    const districtSelect = document.querySelector("#District");

    if (!stateSelect || !districtSelect) {
        throw new Error("State or District dropdown not found.");
    }

    const sleep = ms =>
        new Promise(resolve => setTimeout(resolve, ms));

    // ---------------------------------------------
    // Get all states
    // ---------------------------------------------

    const states = [...stateSelect.options]
        .map(option => ({
            value: option.value.trim(),
            text: option.text.trim()
        }))
        .filter(option =>
            option.value &&
            option.text &&
            option.text.toLowerCase() !== "select"
        );

    console.log(`Found ${states.length} states`);

    const result = [];

    // ---------------------------------------------
    // Process each state
    // ---------------------------------------------

    for (let i = 0; i < states.length; i++) {

        const state = states[i];

        console.log(
            `[${i + 1}/${states.length}] ${state.text}`
        );

        // Existing district values before changing state
        const oldDistrictValues = [...districtSelect.options]
            .map(o => o.value);

        // Select state
        stateSelect.value = state.value;

        // Trigger Vue/browser change event
        stateSelect.dispatchEvent(
            new Event("change", {
                bubbles: true
            })
        );

        // -----------------------------------------
        // Wait for District dropdown to update
        // -----------------------------------------

        let districts = [];

        for (let attempt = 0; attempt < 50; attempt++) {

            await sleep(200);

            districts = [...districtSelect.options]
                .map(option => ({
                    value: option.value.trim(),
                    text: option.text.trim()
                }))
                .filter(option =>
                    option.value &&
                    option.text &&
                    option.text.toLowerCase() !== "select"
                );

            if (districts.length > 0) {

                // Make sure Vue has actually changed
                const newValues = districts.map(d => d.value);

                if (
                    JSON.stringify(newValues) !==
                    JSON.stringify(oldDistrictValues)
                ) {
                    break;
                }
            }
        }

        console.log(
            `   → ${districts.length} districts`
        );

        result.push({
            state_code: state.value,
            state: state.text,
            districts: districts
        });
    }

    // ---------------------------------------------
    // Build final object
    // ---------------------------------------------

    const output = {
        source: "Udyam",
        extracted_at: new Date().toISOString(),
        total_states: result.length,
        total_districts: result.reduce(
            (total, state) =>
                total + state.districts.length,
            0
        ),
        states: result
    };

    // ---------------------------------------------
    // Store globally
    // ---------------------------------------------

    window.UDYAM_STATE_DISTRICT = output;

    // ---------------------------------------------
    // Print JSON
    // ---------------------------------------------

    console.log(
        "=============================================="
    );

    console.log(
        JSON.stringify(output, null, 2)
    );

    console.log(
        "=============================================="
    );

    // ---------------------------------------------
    // Download JSON
    // ---------------------------------------------

    const json = JSON.stringify(output, null, 2);

    const blob = new Blob(
        [json],
        { type: "application/json" }
    );

    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");

    a.href = url;
    a.download = "udyam_state_district.json";

    document.body.appendChild(a);

    a.click();

    a.remove();

    URL.revokeObjectURL(url);

    console.log(
        "✅ Downloaded: udyam_state_district.json"
    );

})();