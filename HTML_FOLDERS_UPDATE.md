# Обновление HTML для поддержки папок

## Вариант 1: Простое обновление (рекомендуется)

Самый простой способ — скачать обновлённый HTML из Artifacts и заменить файл:

```bash
# Замените instagram-monitor.html на новую версию
docker compose down
cp instagram-monitor-with-folders.html instagram-monitor.html
docker compose up -d
```

---

## Вариант 2: Ручное добавление поддержки папок

Если хотите обновить существующий HTML вручную, добавьте следующий код:

### 1. Добавить стили для папок (в секцию `<style>`)

```css
/* Папки */
.folders-section {
    margin-bottom: 16px;
}

.folder-item {
    background: var(--tg-theme-secondary-bg-color, #f5f5f5);
    border-radius: 12px;
    padding: 12px 16px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    transition: opacity 0.2s;
}

.folder-item:active {
    opacity: 0.7;
}

.folder-item.active {
    background: var(--tg-theme-button-color, #0088cc);
    color: white;
}

.folder-icon {
    font-size: 20px;
}

.folder-name {
    flex: 1;
    font-weight: 500;
}

.folder-count {
    font-size: 12px;
    opacity: 0.7;
}

.btn-icon {
    padding: 6px;
    background: rgba(0,0,0,0.1);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
}

.add-folder-btn {
    width: 100%;
    padding: 12px;
    background: transparent;
    border: 2px dashed var(--tg-theme-hint-color, #ddd);
    border-radius: 12px;
    color: var(--tg-theme-hint-color, #999);
    cursor: pointer;
    font-size: 14px;
}

.folder-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    margin-left: 8px;
}
```

### 2. Добавить HTML-разметку для папок (перед секцией конкурентов)

```html
<div class="folders-section">
    <h2 class="section-title">📁 Папки</h2>
    <div id="foldersList"></div>
    <button class="add-folder-btn" onclick="showAddFolderPrompt()">
        ➕ Создать папку
    </button>
</div>
```

### 3. Добавить переменные в JavaScript

```javascript
let folders = [];
let selectedFolderId = null;  // null = показать все
```

### 4. Добавить функции для работы с папками

```javascript
async function fetchFolders() {
    try {
        const response = await fetch(`${API_URL}/folders`, {
            headers: { 'X-User-Id': USER_ID }
        });
        const data = await response.json();
        if (data.success) {
            folders = data.data;
            renderFolders();
        }
    } catch (error) {
        console.error('Ошибка загрузки папок:', error);
    }
}

async function createFolder(name, color = '#0088cc', icon = '📁') {
    try {
        const response = await fetch(`${API_URL}/folders`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Id': USER_ID
            },
            body: JSON.stringify({ name, color, icon })
        });
        const data = await response.json();
        if (data.success) {
            await fetchFolders();
            return data.data.id;
        } else {
            showAlert(data.error || 'Ошибка создания папки');
        }
    } catch (error) {
        console.error('Ошибка:', error);
        showAlert('Ошибка подключения к серверу');
    }
}

async function deleteFolder(folderId, folderName) {
    showConfirm(`Удалить папку "${folderName}"?`, async (confirmed) => {
        if (confirmed) {
            try {
                const response = await fetch(`${API_URL}/folders/${folderId}`, {
                    method: 'DELETE',
                    headers: { 'X-User-Id': USER_ID }
                });
                if (response.ok) {
                    if (selectedFolderId === folderId) {
                        selectedFolderId = null;
                    }
                    await fetchFolders();
                    await fetchCompetitors();
                }
            } catch (error) {
                console.error('Ошибка удаления папки:', error);
            }
        }
    });
}

function renderFolders() {
    const list = document.getElementById('foldersList');
    
    if (folders.length === 0) {
        list.innerHTML = '';
        return;
    }

    list.innerHTML = folders.map(f => `
        <div class="folder-item ${selectedFolderId === f.id ? 'active' : ''}" 
             onclick="selectFolder(${f.id})">
            <div class="folder-icon">${f.icon}</div>
            <div class="folder-name">${f.name}</div>
            <div class="folder-count">${f.count}</div>
            <button class="btn-icon" onclick="event.stopPropagation(); deleteFolder(${f.id}, '${f.name}')">🗑️</button>
        </div>
    `).join('');
}

function selectFolder(folderId) {
    selectedFolderId = selectedFolderId === folderId ? null : folderId;
    renderFolders();
    renderCompetitors();
}

function showAddFolderPrompt() {
    const name = prompt('Название папки:');
    if (name && name.trim()) {
        createFolder(name.trim());
    }
}
```

### 5. Обновить renderCompetitors для фильтрации

```javascript
function renderCompetitors() {
    const list = document.getElementById('competitorsList');
    
    // Фильтруем по выбранной папке
    let filteredCompetitors = competitors;
    if (selectedFolderId !== null) {
        filteredCompetitors = competitors.filter(c => c.folderId === selectedFolderId);
    }
    
    if (filteredCompetitors.length === 0) {
        const message = selectedFolderId !== null 
            ? 'В этой папке пока нет конкурентов'
            : 'Добавьте первого конкурента';
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <div>${message}</div>
            </div>
        `;
        return;
    }

    list.innerHTML = filteredCompetitors.map(c => {
        // Показываем badge папки только когда отображаем всех
        const folder = folders.find(f => f.id === c.folderId);
        const folderBadge = folder && selectedFolderId === null
            ? `<span class="folder-badge" style="background: ${folder.color}20; color: ${folder.color}">${folder.name}</span>`
            : '';
            
        return `
            <div class="competitor-card">
                <div class="competitor-header">
                    <div class="competitor-name">@${c.username}${folderBadge}</div>
                    <button class="btn-remove" onclick="removeCompetitor('${c.username}')">
                        Удалить
                    </button>
                </div>
                <div class="stats">
                    <div class="stat-item">
                        Ср. просмотры: <span class="stat-value">${formatNumber(c.avgViews)}</span>
                    </div>
                    <div class="stat-item">
                        Ср. лайки: <span class="stat-value">${formatNumber(c.avgLikes)}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}
```

### 6. Обновить addCompetitor для поддержки folder_id

```javascript
async function addCompetitor() {
    const username = document.getElementById('usernameInput').value.trim();
    
    if (!username) {
        showAlert('Введите username');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/competitors`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Id': USER_ID
            },
            body: JSON.stringify({ 
                username,
                folder_id: selectedFolderId  // ← добавить эту строку
            })
        });
        // ... остальной код
    }
}
```

### 7. Обновить init() для загрузки папок

```javascript
async function init() {
    await registerUser();
    await fetchFolders();  // ← добавить эту строку
    await fetchCompetitors();
    await fetchAlerts();
    updateLastCheck();
}
```

---

## Вариант 3: Работа без UI папок

Если не хотите обновлять HTML, папки всё равно работают через API:

```bash
# Создать папку "Спорт"
curl -X POST http://localhost/api/folders \
  -H "Content-Type: application/json" \
  -H "X-User-Id: telegram_123" \
  -d '{"name": "Спорт", "icon": "⚽"}'

# Добавить конкурента в папку
curl -X POST http://localhost/api/competitors \
  -H "Content-Type: application/json" \
  -H "X-User-Id: telegram_123" \
  -d '{"username": "nike", "folder_id": 1}'
```

В API `/api/competitors` конкуренты будут возвращаться с полем `folderId`, которое можно использовать для группировки на клиенте.

---

## Тестирование

После обновления HTML:

1. Откройте приложение
2. Создайте папку "Тест" (кнопка "Создать папку")
3. Добавьте конкурента — он должен попасть в выбранную папку
4. Кликните по папке — отфильтруются только её конкуренты
5. Удалите папку — конкуренты останутся, но перейдут в "Без папки"
