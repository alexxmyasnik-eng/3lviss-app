document.addEventListener('DOMContentLoaded', function() {
    
    // ----- ИНИЦИАЛИЗАЦИЯ TELEGRAM -----
    // Получаем доступ к API, предоставленному telegram-web-app.js
    const tg = window.Telegram.WebApp;
    // Говорим Telegram, что наше приложение готово к показу
    tg.ready();

    // ----- ЭЛЕМЕНТЫ СТРАНИЦЫ -----
    const homeScreen = document.getElementById('home-screen');
    const caseDetailScreen = document.getElementById('case-detail-screen');
    const backButton = document.getElementById('back-button');
    const caseCards = document.querySelectorAll('.case-card');
    const openCaseButton = document.querySelector('#case-detail-screen .action-button');
    
    // Элементы профиля, которые мы будем обновлять
    const userAvatarElement = document.querySelector('.user-profile .avatar');
    const usernameElement = document.querySelector('.user-profile .username');

    // ----- ИМИТАЦИЯ БЭКЕНДА И ДАННЫХ -----

    // "Фальшивая" база данных, которая будет хранить балансы
    let fakeDatabase = {}; 

    // Получаем реальные данные пользователя от Telegram
    // initDataUnsafe содержит информацию о пользователе, открывшем приложение
    const user = tg.initDataUnsafe.user;
    
    let currentUser;
    let CURRENT_USER_ID;

    if (user) {
        // Если данные пользователя есть (мы в Telegram)
        CURRENT_USER_ID = user.id.toString();
        
        // Проверяем, есть ли этот пользователь в нашей "базе"
        if (!fakeDatabase[CURRENT_USER_ID]) {
            // Если нет, создаем для него запись с начальным балансом
            fakeDatabase[CURRENT_USER_ID] = {
                name: user.first_name, // Берем имя из Telegram
                balance: 1000 // Стартовый баланс для новых игроков
            };
        }
        currentUser = fakeDatabase[CURRENT_USER_ID];
        
        // Обновляем аватарку и имя на странице
        usernameElement.textContent = currentUser.name;
        // Telegram не дает прямую ссылку на аватар, поэтому пока оставляем заглушку.
        // Чтобы получить фото, нужен более сложный запрос к вашему Python-серверу.
        // Мы сделаем это на следующем шаге.
        // userAvatarElement.src = user.photo_url || 'https://via.placeholder.com/48';

    } else {
        // Если мы открыли страницу в обычном браузере (не в Telegram)
        usernameElement.textContent = "Тестовый режим";
        // Создаем тестового пользователя для отладки
        CURRENT_USER_ID = 'test_user';
        if (!fakeDatabase[CURRENT_USER_ID]) {
            fakeDatabase[CURRENT_USER_ID] = { name: 'Тестер', balance: 500 };
        }
        currentUser = fakeDatabase[CURRENT_USER_ID];
    }

    // Функция для обновления отображения баланса
    function updateBalanceDisplay() {
        // Теперь баланс показывается вместе с именем
        usernameElement.textContent = `${currentUser.name} | ${currentUser.balance} ⭐`;
    }

    // "Мозги": функция открытия кейса
    function processCaseOpening(cost) {
        if (currentUser.balance >= cost) {
            currentUser.balance -= cost;
            updateBalanceDisplay();
            tg.HapticFeedback.notificationOccurred('success'); // Приятная вибрация при успехе
            alert(`Кейс открыт! Остаток: ${currentUser.balance} ⭐`);
        } else {
            tg.HapticFeedback.notificationOccurred('error'); // Вибрация при ошибке
            alert(`Ошибка! Недостаточно средств. Нужно: ${cost} ⭐`);
        }
    }

    // ----- ЛОГИКА ПЕРЕКЛЮЧЕНИЯ ЭКРАНОВ -----
    function showScreen(screenToShow) {
        homeScreen.classList.remove('active'); caseDetailScreen.classList.remove('active');
        screenToShow.classList.add('active');
    }
    caseCards.forEach(card => card.addEventListener('click', () => showScreen(caseDetailScreen)));
    backButton.addEventListener('click', () => showScreen(homeScreen));
    openCaseButton.addEventListener('click', () => {
        const caseCost = 222;
        processCaseOpening(caseCost);
    });

    // ----- ИНИЦИАЛИЗАЦИЯ ПРИ ЗАПУСКЕ -----
    updateBalanceDisplay(); 

});

