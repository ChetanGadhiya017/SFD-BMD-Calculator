// Add / remove load rows and toggle support inputs for cantilevers.
document.querySelectorAll(".add").forEach((btn) => {
  btn.addEventListener("click", () => {
    const box = document.querySelector(`.rows[data-group="${btn.dataset.target}"]`);
    const row = document.createElement("div");
    row.className = "load";
    box.dataset.fields.split(",").forEach((pair) => {
      const [field, label] = pair.split(":");
      const input = document.createElement("input");
      Object.assign(input, { type: "number", step: "any", placeholder: label, name: `${box.dataset.group}_${field}` });
      row.appendChild(input);
    });
    const del = document.createElement("button");
    Object.assign(del, { type: "button", className: "del", textContent: "✕" });
    del.setAttribute("aria-label", "Remove");
    row.appendChild(del);
    box.appendChild(row);
    row.querySelector("input").focus();
  });
});

document.addEventListener("click", (e) => {
  if (e.target.classList.contains("del")) e.target.closest(".load").remove();
});

const kind = document.getElementById("kind");
const supports = document.querySelector(".supports");
const sync = () => supports.classList.toggle("hidden", kind.value === "cantilever");
kind.addEventListener("change", sync);
sync();
