// Nav Bounce Effect - D3.js rubber band physics
document.addEventListener('DOMContentLoaded', function () {
    // Load D3.js dynamically
    const d3Script = document.createElement('script');
    d3Script.src = 'https://d3js.org/d3.v7.min.js';
    d3Script.onload = initBounce;
    document.head.appendChild(d3Script);

    function initBounce() {
        const navLinks = document.querySelectorAll('.nav-link');

        navLinks.forEach(link => {
            // Store original position
            let originalY = 0;
            let velocity = 0;
            let isHovering = false;
            let animationId = null;

            // Spring physics constants
            const springConstant = 0.15;
            const damping = 0.7;
            const bounceStrength = 15;

            // Get original position on first interaction
            link.addEventListener('mouseenter', function () {
                if (!originalY) {
                    originalY = parseFloat(getComputedStyle(link).marginTop) || 0;
                }
                isHovering = true;

                // Apply initial bounce impulse
                velocity = -bounceStrength;

                // Start animation if not already running
                if (!animationId) {
                    animate();
                }
            });

            link.addEventListener('mouseleave', function () {
                isHovering = false;
            });

            function animate() {
                const currentY = parseFloat(link.style.marginTop) || 0;

                // Spring force pulls back to original position
                const displacement = currentY;
                const springForce = -springConstant * displacement;

                // Apply damping
                velocity += springForce;
                velocity *= damping;

                // Update position
                const newY = currentY + velocity;
                link.style.marginTop = newY + 'px';

                // Add subtle rotation for rubber effect
                const rotation = newY * 0.5;
                link.style.transform = `rotate(${rotation}deg)`;

                // Continue animation if still moving or hovering
                if (Math.abs(velocity) > 0.01 || Math.abs(newY) > 0.01 || isHovering) {
                    animationId = requestAnimationFrame(animate);
                } else {
                    // Reset when settled
                    link.style.marginTop = '';
                    link.style.transform = '';
                    animationId = null;
                }
            }
        });

        // Add click bounce effect
        navLinks.forEach(link => {
            link.addEventListener('mousedown', function (e) {
                // Quick squish effect
                d3.select(link)
                    .transition()
                    .duration(50)
                    .style('transform', 'scale(0.95)')
                    .transition()
                    .duration(100)
                    .style('transform', 'scale(1.05)')
                    .transition()
                    .duration(75)
                    .style('transform', 'scale(1)');
            });
        });
    }
});