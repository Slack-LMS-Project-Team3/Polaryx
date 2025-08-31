CREATE DATABASE IF NOT EXISTS polaryx;
USE polaryx;

CREATE TABLE IF NOT EXISTS `canvases` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `tab_id` bigint(20) NOT NULL,
  `page_id` varchar(256) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_canvas` (`workspace_id`, `tab_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `emoji` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `e_check` smallint(6) DEFAULT '0',
  `e_clap` smallint(6) DEFAULT '0',
  `e_like` smallint(6) DEFAULT '0',
  `e_pray` smallint(6) DEFAULT '0',
  `e_sparkle` smallint(6) DEFAULT '0',
  `msg_id` bigint(20) NOT NULL,
  `user_id` binary(16) NOT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS  `group_members` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `group_id` int(11) NOT NULL,
  `user_id` binary(16) NOT NULL,
  `user_name` varchar(32) DEFAULT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_group_user` (`group_id`,`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=35 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `groups` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(32) NOT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `links` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tab_id` bigint(20) NOT NULL,
  `sender_id` binary(16) NOT NULL,
  `link_url` text NOT NULL,
  `link_favicon` text,
  `link_name` varchar(255) CHARACTER SET utf8mb4 DEFAULT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `member_roles` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` binary(16) NOT NULL,
  `role_id` int(11) NOT NULL,
  `user_name` varchar(32) DEFAULT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_role_user` (`role_id`,`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=36 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `messages` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tab_id` bigint(20) NOT NULL,
  `sender_id` binary(16) NOT NULL,
  `content` text NOT NULL,
  `is_updated` tinyint(1) DEFAULT '0',
  `sender_name` varchar(32) DEFAULT NULL,
  `url` varchar(256) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  `check_cnt` int(11) DEFAULT '0',
  `clap_cnt` int(11) DEFAULT '0',
  `like_cnt` int(11) DEFAULT '0',
  `sparkle_cnt` int(11) DEFAULT '0',
  `pray_cnt` int(11) DEFAULT '0',
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=255 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `notifications` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `receiver_id` binary(16) NOT NULL,
  `sender_id` binary(16) NOT NULL,
  `tab_id` bigint(20) NOT NULL,
  `message_id` bigint(20) NOT NULL,
  `type` int(11) NOT NULL,
  `content` varchar(255) NOT NULL,
  `is_read` tinyint(1) DEFAULT '0',
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `read_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1540 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `push_subscriptions` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` binary(16) NOT NULL,
  `endpoint` text NOT NULL,
  `p256dh` text NOT NULL,
  `auth` text NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_push_sub` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=343 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `refresh_tokens` (
  `id` binary(16) NOT NULL,
  `user_id` binary(16) NOT NULL,
  `token` varchar(255) NOT NULL,
  `user_name` varchar(32) DEFAULT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `roles` (
  `id` int(11) NOT NULL,
  `name` varchar(32) NOT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `admin` tinyint(1) NOT NULL,
  `announce` tinyint(1) NOT NULL,
  `course` tinyint(1) NOT NULL,
  `channel` tinyint(1) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  UNIQUE KEY `uq_role` (`id`,`workspace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `save_messages` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` binary(16) NOT NULL,
  `workspace_id` bigint(20) NOT NULL DEFAULT 1,
  `content` mediumtext NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `sections` (
  `id` int(11) NOT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `name` varchar(64) NOT NULL,
  UNIQUE KEY `uq_section` (`id`,`workspace_id`,`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `tab_members` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `user_id` binary(16) NOT NULL,
  `tab_id` bigint(20) NOT NULL,
  `user_name` varchar(32) DEFAULT NULL,
  `visited_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_tab_member` (`user_id`,`tab_id`,`workspace_id`)
) ENGINE=InnoDB AUTO_INCREMENT=569 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `tabs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(64) NOT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `section_id` int(11) NOT NULL,
  `url` varchar(256) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=381 DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `users` (
  `id` binary(16) NOT NULL,
  `name` varchar(32) NOT NULL,
  `email` varchar(128) NOT NULL,
  `provider` varchar(16) NOT NULL,
  `provider_id` varchar(255) DEFAULT NULL,
  `workspace_id` int(11) DEFAULT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_email_provider_ws` (`email`,`provider`,`workspace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `workspace_members` (
  `id` binary(16) NOT NULL,
  `user_id` binary(16) NOT NULL,
  `workspace_id` int(11) NOT NULL DEFAULT 1,
  `nickname` varchar(32) NOT NULL,
  `email` varchar(128) NOT NULL,
  `image` varchar(255) DEFAULT NULL,
  `github` varchar(255) DEFAULT NULL,
  `blog` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_workspace` (`user_id`,`workspace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `workspaces` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(32) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL,
  `deleted_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4;