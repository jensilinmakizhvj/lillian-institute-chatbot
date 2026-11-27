
// Lillian Institute site navigation and lightweight UI interactions.
(() => {
  const menuToggle = document.getElementById('menuToggle');
  const mainNav = document.getElementById('mainNav');

  if (menuToggle && mainNav) {
    menuToggle.addEventListener('click', () => {
      const isOpen = mainNav.classList.toggle('open');
      menuToggle.setAttribute('aria-expanded', String(isOpen));
    });

    mainNav.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        mainNav.classList.remove('open');
        menuToggle.setAttribute('aria-expanded', 'false');
      });
    });
  }
})();

// Load faculty names department-wise.
document.addEventListener('DOMContentLoaded', async () => {
  const directory = document.getElementById('facultyDirectory');
  if (!directory) return;

  directory.innerHTML = '<p>Loading faculty members...</p>';

  try {
    const response = await fetch('/api/public-faculty');

    if (!response.ok) {
      throw new Error('Faculty API error: ' + response.status);
    }

    const result = await response.json();
    const faculty = result.faculty || [];

    if (result.status !== 'success' || faculty.length === 0) {
      directory.innerHTML = '<p>No faculty details available.</p>';
      return;
    }

    const departments = {};

    faculty.forEach(member => {
      const department = (member.department || 'Other').trim();

      if (!departments[department]) {
        departments[department] = [];
      }

      departments[department].push(member);
    });

    directory.replaceChildren();

    Object.keys(departments).sort().forEach(department => {
      const group = document.createElement('section');
      group.className = 'faculty-department-group';

      const heading = document.createElement('h4');
      heading.className = 'faculty-department-title';
      heading.textContent = department;

      const grid = document.createElement('div');
      grid.className = 'faculty-directory-grid';

      departments[department].forEach(member => {
        const card = document.createElement('article');
        card.className = 'faculty-directory-card';

        const role = document.createElement('span');
        role.className = 'faculty-directory-role';
        role.textContent = member.designation || 'Faculty';

        const name = document.createElement('h5');
        name.className = 'faculty-directory-name';
        name.textContent = member.name || 'Name not available';

        card.append(role, name);
        grid.appendChild(card);
      });

      group.append(heading, grid);
      directory.appendChild(group);
    });

  } catch (error) {
    console.error('Faculty loading error:', error);
    directory.innerHTML =
      '<p>Unable to load faculty members. Please check the backend.</p>';
  }
});
