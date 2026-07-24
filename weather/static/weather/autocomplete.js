const CITY_AUTOCOMPLETE = (() => {
    let cities = [];
    let loaded = false;
    let activeIndex = -1;

    async function loadCities() {
        try {
            const resp = await fetch('/static/weather/worldcities.csv');
            const text = await resp.text();
            cities = text.split('\n').slice(1).map(c => c.trim()).filter(Boolean);
            cities.sort((a, b) => a.localeCompare(b));
            loaded = true;
        } catch (e) {
            console.warn('Could not load city list:', e);
        }
    }

    function createDropdown(input) {
        const wrapper = document.createElement('div');
        wrapper.className = 'autocomplete-wrapper';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const list = document.createElement('ul');
        list.className = 'autocomplete-list';
        wrapper.appendChild(list);

        return { wrapper, list };
    }

    function filterCities(query) {
        if (!query || query.length < 2) return [];
        const q = query.toLowerCase();
        const results = [];
        for (let i = 0; i < cities.length && results.length < 8; i++) {
            if (cities[i].toLowerCase().startsWith(q)) {
                results.push(cities[i]);
            }
        }
        return results;
    }

    function renderList(list, input, matches) {
        list.innerHTML = '';
        activeIndex = -1;

        if (matches.length === 0) {
            list.style.display = 'none';
            return;
        }

        matches.forEach((city, i) => {
            const li = document.createElement('li');
            li.className = 'autocomplete-item';
            li.textContent = city;
            li.addEventListener('mousedown', (e) => {
                e.preventDefault();
                input.value = city;
                list.style.display = 'none';
            });
            list.appendChild(li);
        });

        list.style.display = 'block';
    }

    function init() {
        const input = document.querySelector('.modal-form input[name="city"]');
        if (!input) return;

        const { list } = createDropdown(input);

        input.setAttribute('autocomplete', 'off');

        input.addEventListener('input', () => {
            if (!loaded) return;
            const matches = filterCities(input.value);
            renderList(list, input, matches);
        });

        input.addEventListener('keydown', (e) => {
            const items = list.querySelectorAll('.autocomplete-item');
            if (items.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIndex = Math.min(activeIndex + 1, items.length - 1);
                items.forEach((el, i) => el.classList.toggle('active', i === activeIndex));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
                items.forEach((el, i) => el.classList.toggle('active', i === activeIndex));
            } else if (e.key === 'Enter' && activeIndex >= 0) {
                e.preventDefault();
                input.value = items[activeIndex].textContent;
                list.style.display = 'none';
            } else if (e.key === 'Escape') {
                list.style.display = 'none';
            }
        });

        input.addEventListener('blur', () => {
            setTimeout(() => { list.style.display = 'none'; }, 150);
        });

        input.addEventListener('focus', () => {
            if (input.value.length >= 2) {
                const matches = filterCities(input.value);
                renderList(list, input, matches);
            }
        });

        loadCities();
    }

    return { init };
})();

document.addEventListener('DOMContentLoaded', CITY_AUTOCOMPLETE.init);
