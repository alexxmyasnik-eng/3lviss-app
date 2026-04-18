document.addEventListener('DOMContentLoaded', function() {
    
    const homeScreen = document.getElementById('home-screen');
    const caseDetailScreen = document.getElementById('case-detail-screen');
    const backButton = document.getElementById('back-button');
    const caseCards = document.querySelectorAll('.case-card');

    // Функция для переключения экранов
    function showScreen(screenToShow) {
        homeScreen.classList.remove('active');
        caseDetailScreen.classList.remove('active');
        screenToShow.classList.add('active');
    }

    // При клике на карточку кейса
    caseCards.forEach(card => {
        card.addEventListener('click', () => {
            // В будущем здесь можно будет загружать данные конкретного кейса
            // const caseId = card.dataset.caseId;
            // console.log('Открываем кейс с ID:', caseId);
            showScreen(caseDetailScreen);
        });
    });

    // При клике на кнопку "Назад"
    backButton.addEventListener('click', () => {
        showScreen(homeScreen);
    });

});
