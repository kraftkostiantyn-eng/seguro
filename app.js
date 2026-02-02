const calcForm = document.getElementById("calc-form");
const leadForm = document.getElementById("lead-form");
const resultCards = document.getElementById("result-cards");
const toast = document.getElementById("toast");

const basePlans = {
  medical: [18, 29, 41],
  auto: [22, 36, 52],
  home: [16, 24, 38],
  life: [14, 21, 35],
};

const coverageLabels = {
  basic: "€30 000",
  standard: "€60 000",
  premium: "€150 000",
};

const planNames = ["Seguro Base", "Seguro Smart", "Seguro Plus"];

const getMultiplier = ({ age, coverage, expat, family }) => {
  let multiplier = 1;
  if (age > 45) multiplier += 0.2;
  if (age > 60) multiplier += 0.35;
  if (coverage === "premium") multiplier += 0.25;
  if (coverage === "standard") multiplier += 0.1;
  if (expat) multiplier += 0.1;
  if (family) multiplier += 0.15;
  return multiplier;
};

const formatEuro = (value) => `€${value}/мес`;

const buildCard = ({ name, price, coverage, features, highlight }) => {
  const card = document.createElement("div");
  card.className = `result-card${highlight ? " highlight" : ""}`;
  card.innerHTML = `
    <h4>${name}</h4>
    <p class="price">${price}</p>
    <ul>
      ${features.map((feature) => `<li>${feature}</li>`).join("")}
    </ul>
    <button class="${highlight ? "cta" : "ghost"}">${highlight ? "Оформить" : "Оставить заявку"}</button>
  `;
  return card;
};

calcForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(calcForm);
  const type = data.get("type");
  const age = Number(data.get("age"));
  const coverage = data.get("coverage");
  const expat = data.get("expat") === "on";
  const family = data.get("family") === "on";

  const multiplier = getMultiplier({ age, coverage, expat, family });
  const base = basePlans[type];

  resultCards.innerHTML = "";

  base.forEach((price, index) => {
    const adjusted = Math.round(price * multiplier);
    const card = buildCard({
      name: planNames[index],
      price: formatEuro(adjusted),
      coverage: coverageLabels[coverage],
      features: [
        `Покрытие ${coverageLabels[coverage]}`,
        expat ? "Подходит для ВНЖ" : "Гибкая настройка опций",
        family ? "Семейный пакет" : "Персональный менеджер",
      ],
      highlight: index === 1,
    });
    resultCards.appendChild(card);
  });
});

leadForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  toast.classList.add("show");
  leadForm.reset();
  setTimeout(() => toast.classList.remove("show"), 3000);
});
