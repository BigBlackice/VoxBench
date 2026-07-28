() => {
    if (window.__voxbenchDocumentQueueInstalled) return [];
    window.__voxbenchDocumentQueueInstalled = true;

    let draggedRow = null;
    let dragArmed = false;

    const sendOrder = (tbody) => {
        const order = [...tbody.querySelectorAll("tr")]
            .map((row) => row.cells[2]?.textContent.trim())
            .filter(Boolean)
            .join(",");
        const field = document.querySelector(
            "#document_queue_order textarea, #document_queue_order input"
        );
        if (!field || !order) return;
        const setter = Object.getOwnPropertyDescriptor(
            Object.getPrototypeOf(field),
            "value"
        )?.set;
        if (setter) setter.call(field, order);
        else field.value = order;
        field.dispatchEvent(new Event("input", { bubbles: true }));
    };

    const prepareRows = () => {
        const tbody = document.querySelector("#document_outline table tbody");
        if (!tbody) return;
        for (const row of tbody.querySelectorAll("tr")) {
            if (row.dataset.queueDragReady) continue;
            row.dataset.queueDragReady = "true";
            row.classList.add("queue-draggable");
            row.draggable = true;

            const handle = row.cells[0];
            handle?.addEventListener("pointerdown", () => {
                dragArmed = true;
            });

            row.addEventListener("dragstart", (event) => {
                if (!dragArmed) {
                    event.preventDefault();
                    return;
                }
                draggedRow = row;
                row.classList.add("queue-dragging");
                event.dataTransfer.effectAllowed = "move";
            });
            row.addEventListener("dragover", (event) => {
                if (!draggedRow || draggedRow === row) return;
                event.preventDefault();
                row.classList.add("queue-drag-over");
                event.dataTransfer.dropEffect = "move";
            });
            row.addEventListener("dragleave", () => {
                row.classList.remove("queue-drag-over");
            });
            row.addEventListener("drop", (event) => {
                event.preventDefault();
                row.classList.remove("queue-drag-over");
                if (!draggedRow || draggedRow === row) return;
                const rows = [...tbody.children];
                const targetIndex = rows.indexOf(row);
                const draggedIndex = rows.indexOf(draggedRow);
                tbody.insertBefore(
                    draggedRow,
                    draggedIndex < targetIndex ? row.nextSibling : row
                );
                sendOrder(tbody);
            });
            row.addEventListener("dragend", () => {
                row.classList.remove("queue-dragging");
                for (const item of tbody.querySelectorAll(".queue-drag-over")) {
                    item.classList.remove("queue-drag-over");
                }
                draggedRow = null;
                dragArmed = false;
            });
            row.addEventListener("pointerup", () => {
                if (!draggedRow) dragArmed = false;
            });
        }
    };

    const observer = new MutationObserver(prepareRows);
    observer.observe(document.body, { childList: true, subtree: true });
    prepareRows();
    return [];
}
