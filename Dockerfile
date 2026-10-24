FROM eclipse-temurin:17-jdk AS build
WORKDIR /build
COPY gradlew build.gradle settings.gradle ./
COPY gradle ./gradle
COPY src ./src
RUN chmod +x gradlew && ./gradlew --no-daemon bootJar -x test

FROM eclipse-temurin:17-jre
WORKDIR /app
RUN groupadd --system parliament && useradd --system --gid parliament parliament
COPY --from=build /build/build/libs/*.jar /app/application.jar
USER parliament
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=35", "-jar", "/app/application.jar"]
